# -*- coding: utf-8 -*-
"""
元数据同步脚本：YAML → Meta MySQL

职责：
    1. 加载 config/metadata/ 下全部 YAML（表元数据文件 + metrics.yaml 指标文件）
    2. Schema 校验：必填字段缺失、类型错误时中断并指出具体文件与原因
    3. 幂等同步到 meta_db：
       - 表：按 table_name upsert
       - 字段：按 (table_id, field_name) upsert，并删除 YAML 中已移除的字段（diff 同步）
       - 指标：按 metric_name upsert
    4. 每个文件写入 meta_sync_log 同步日志
    5. 输出同步统计

运行方式（项目根目录）：
    python scripts/sync_meta.py
"""
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logger import logger, setup_logger
from app.models.meta import MetaBase, MetaField, MetaMetric, MetaSyncLog, MetaTable

METADATA_DIR = Path("config/metadata")


# =====================================================================
# YAML 加载与校验
# =====================================================================
def load_table_yaml(path: Path) -> dict:
    """加载并校验单张表元数据 YAML

    Args:
        path: YAML 文件路径

    Returns:
        解析后的表元数据字典

    Raises:
        ValueError: 校验失败时抛出，附具体原因
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "table" not in data or "fields" not in data:
        raise ValueError("缺少 table 或 fields 顶层节点")

    table = data["table"]
    for key in ("name", "alias", "desc", "layer"):
        if not table.get(key):
            raise ValueError(f"table 缺少必填字段: {key}")

    if table["layer"] not in ("ods", "dw", "dm"):
        raise ValueError(f"layer 非法: {table['layer']}，应为 ods/dw/dm")

    if not isinstance(data["fields"], list) or len(data["fields"]) == 0:
        raise ValueError("fields 不能为空")

    seen = set()
    for i, field in enumerate(data["fields"], start=1):
        for key in ("name", "alias", "desc", "type"):
            if not field.get(key):
                raise ValueError(f"第 {i} 个字段缺少必填项: {key}")
        if field["name"] in seen:
            raise ValueError(f"字段名重复: {field['name']}")
        seen.add(field["name"])
        if "searchable" not in field:
            field["searchable"] = False  # 默认不参与取值全文索引

    return data


def load_metric_yaml(path: Path) -> list[dict]:
    """加载并校验指标口径 YAML

    Args:
        path: YAML 文件路径

    Returns:
        指标字典列表

    Raises:
        ValueError: 校验失败时抛出，附具体原因
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "metrics" not in data:
        raise ValueError("缺少 metrics 顶层节点")

    metrics = data["metrics"]
    if not isinstance(metrics, list) or len(metrics) == 0:
        raise ValueError("metrics 不能为空")

    seen = set()
    for i, metric in enumerate(metrics, start=1):
        for key in ("name", "desc", "formula", "table"):
            if not metric.get(key):
                raise ValueError(f"第 {i} 个指标缺少必填项: {key}")
        if not metric.get("alias"):
            raise ValueError(f"指标 {metric['name']} 缺少别名列表 alias")
        if metric["name"] in seen:
            raise ValueError(f"指标名重复: {metric['name']}")
        seen.add(metric["name"])

    return metrics


# =====================================================================
# 同步逻辑
# =====================================================================
def upsert_table(session: Session, table_data: dict) -> MetaTable:
    """表级 upsert：按 table_name 查找，存在则更新，否则新建

    Args:
        session: ORM 会话
        table_data: table 节点字典

    Returns:
        对应的 MetaTable ORM 对象
    """
    name = table_data["name"]
    existing = session.execute(
        select(MetaTable).where(MetaTable.table_name == name)
    ).scalar_one_or_none()

    if existing:
        existing.alias = table_data["alias"]
        existing.table_desc = table_data["desc"]
        existing.layer = table_data["layer"]
        existing.owner = table_data.get("owner")
        logger.info("更新表元数据: {}", name)
        return existing

    obj = MetaTable(
        table_name=name,
        alias=table_data["alias"],
        table_desc=table_data["desc"],
        layer=table_data["layer"],
        owner=table_data.get("owner"),
    )
    session.add(obj)
    session.flush()  # 获取自增 ID 供字段外键使用
    logger.info("新建表元数据: {}", name)
    return obj


def sync_fields(session: Session, table_obj: MetaTable, fields: list[dict]) -> dict:
    """字段 diff 同步：upsert YAML 中的字段，删除 DB 中多余字段

    Args:
        session: ORM 会话
        table_obj: 所属表对象
        fields: YAML 字段列表

    Returns:
        {"added": 新增数, "updated": 更新数, "removed": 删除数}
    """
    stats = {"added": 0, "updated": 0, "removed": 0}
    yaml_names = set()

    db_fields = {
        f.field_name: f
        for f in session.execute(
            select(MetaField).where(MetaField.table_id == table_obj.id)
        ).scalars()
    }

    for field in fields:
        name = field["name"]
        yaml_names.add(name)
        examples = field.get("examples") or []
        existing = db_fields.get(name)
        if existing:
            existing.field_alias = field["alias"]
            existing.field_desc = field["desc"]
            existing.field_type = field["type"]
            existing.examples = examples
            existing.searchable = bool(field.get("searchable", False))
            stats["updated"] += 1
        else:
            session.add(
                MetaField(
                    table_id=table_obj.id,
                    field_name=name,
                    field_alias=field["alias"],
                    field_desc=field["desc"],
                    field_type=field["type"],
                    examples=examples,
                    searchable=bool(field.get("searchable", False)),
                )
            )
            stats["added"] += 1

    # 删除 YAML 中已移除的字段（保持元数据与声明一致）
    removed = set(db_fields.keys()) - yaml_names
    if removed:
        session.execute(
            delete(MetaField).where(
                MetaField.table_id == table_obj.id, MetaField.field_name.in_(removed)
            )
        )
        stats["removed"] = len(removed)

    return stats


def upsert_metric(session: Session, metric: dict) -> str:
    """指标 upsert：按 metric_name 查找，存在则更新，否则新建

    Args:
        session: ORM 会话
        metric: 指标字典

    Returns:
        "added" 或 "updated"
    """
    name = metric["name"]
    existing = session.execute(
        select(MetaMetric).where(MetaMetric.metric_name == name)
    ).scalar_one_or_none()

    if existing:
        existing.alias = metric["alias"]
        existing.metric_desc = metric["desc"]
        existing.formula = metric["formula"]
        existing.table_name = metric["table"]
        existing.related_fields = metric.get("related_fields", [])
        return "updated"

    session.add(
        MetaMetric(
            metric_name=name,
            alias=metric["alias"],
            metric_desc=metric["desc"],
            formula=metric["formula"],
            table_name=metric["table"],
            related_fields=metric.get("related_fields", []),
        )
    )
    return "added"


def write_sync_log(session: Session, batch_no: str, yaml_file: str, ok: bool, message: str) -> None:
    """写入同步日志

    Args:
        session: ORM 会话
        batch_no: 批次号
        yaml_file: 来源文件名
        ok: 是否成功
        message: 详情
    """
    session.add(
        MetaSyncLog(
            batch_no=batch_no,
            yaml_file=yaml_file,
            status="success" if ok else "failed",
            message=message[:1000],
        )
    )


def main() -> None:
    """脚本主入口：加载 YAML → 校验 → 建表 → 同步 → 写日志 → 统计输出"""
    setup_logger(level="INFO")
    settings = get_settings()
    engine = create_engine(settings.mysql.url_for(settings.mysql.meta_database))

    # 元数据表不存在时自动建表（幂等）
    MetaBase.metadata.create_all(engine)

    batch_no = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{random.randint(100, 999)}"
    yaml_files = sorted(METADATA_DIR.glob("*.yaml"))
    if not yaml_files:
        logger.error("未找到任何元数据 YAML: {}", METADATA_DIR)
        sys.exit(1)

    total_stats: dict[str, Any] = {"tables": 0, "fields": 0, "metrics": 0, "failed": 0}

    for path in yaml_files:
        logger.info("---- 处理文件: {} ----", path.name)
        try:
            with Session(engine) as session:
                if path.name == "metrics.yaml":
                    # 指标文件
                    metrics = load_metric_yaml(path)
                    for metric in metrics:
                        result = upsert_metric(session, metric)
                        total_stats["metrics"] += 1
                        logger.info("指标 {} : {}", metric["name"], result)
                    session.commit()
                    write_sync_log(session, batch_no, path.name, True, f"{len(metrics)} metrics synced")
                    session.commit()
                else:
                    # 表元数据文件
                    data = load_table_yaml(path)
                    table_obj = upsert_table(session, data["table"])
                    field_stats = sync_fields(session, table_obj, data["fields"])
                    session.commit()
                    total_stats["tables"] += 1
                    total_stats["fields"] += len(data["fields"])
                    logger.info(
                        "字段同步完成: {} (新增 {} 更新 {} 删除 {})",
                        data["table"]["name"], field_stats["added"], field_stats["updated"], field_stats["removed"],
                    )
                    write_sync_log(
                        session, batch_no, path.name, True,
                        f"table={data['table']['name']} fields={field_stats}",
                    )
                    session.commit()
        except Exception as exc:
            # with Session 退出时已自动回滚未提交事务；此处仅记录失败日志与统计
            total_stats["failed"] += 1
            logger.error("文件 {} 同步失败: {}", path.name, exc)
            # 失败也要落日志（独立会话，避免被前面回滚影响）
            with Session(engine) as log_session:
                write_sync_log(log_session, batch_no, path.name, False, str(exc))
                log_session.commit()

    logger.info(
        "========== 同步完成 批次={} | 表 {} | 字段 {} | 指标 {} | 失败 {} ==========",
        batch_no, total_stats["tables"], total_stats["fields"], total_stats["metrics"], total_stats["failed"],
    )
    if total_stats["failed"] > 0:
        sys.exit(1)
    engine.dispose()


if __name__ == "__main__":
    main()
