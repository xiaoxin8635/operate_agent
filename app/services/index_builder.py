# -*- coding: utf-8 -*-
"""
索引构建服务

职责：向量索引（Qdrant）与取值全文索引（ES）的构建逻辑，
供构建脚本（scripts/build_*.py）与管理接口（POST /api/index/rebuild）共用，
保证两条入口的构建行为完全一致。
"""
import re
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.clients import ClientManager
from app.core.config import get_settings
from app.core.logger import logger
from app.models.meta import MetaField, MetaMetric, MetaTable
from app.services import text_search, vector_store
from app.services.embedding import encode_documents

# 标识符白名单（防注入：表/字段名仅允许字母数字下划线）
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

# 向量化文本模板（固定，保证召回一致性）
FIELD_TEMPLATE = "{table_alias}({table_name})的字段{alias}({field_name})：{field_desc}"
METRIC_TEMPLATE = "{metric_name}({alias_str})：{metric_desc}。计算公式：{formula}"


def _load_fields(meta_engine) -> list[dict]:
    """读取全部表字段元数据（表 join 字段）"""
    with Session(meta_engine) as session:
        rows = session.execute(
            select(MetaTable, MetaField).join(MetaField, MetaField.table_id == MetaTable.id)
        ).all()
    return [
        {
            "table_name": t.table_name, "table_alias": t.alias,
            "field_name": f.field_name, "alias": f.field_alias, "field_desc": f.field_desc,
        }
        for t, f in rows
    ]


def _load_metrics(meta_engine) -> list[dict]:
    """读取全部指标元数据"""
    with Session(meta_engine) as session:
        metrics = session.execute(select(MetaMetric)).scalars().all()
    return [
        {
            "metric_name": m.metric_name, "alias": m.alias or [],
            "metric_desc": m.metric_desc, "formula": m.formula, "table_name": m.table_name,
        }
        for m in metrics
    ]


def build_vector_index() -> dict[str, Any]:
    """构建字段与指标向量索引（全量重建）

    Returns:
        {"fields": 字段向量条数, "metrics": 指标向量条数}
    """
    settings = get_settings()
    meta_engine = create_engine(settings.mysql.url_for(settings.mysql.meta_database))

    fields = _load_fields(meta_engine)
    metrics = _load_metrics(meta_engine)
    logger.info("向量索引构建: 字段 {} 条, 指标 {} 条", len(fields), len(metrics))
    if not fields and not metrics:
        raise RuntimeError("元数据为空，请先执行 python scripts/sync_meta.py")

    qdrant = ClientManager.get_qdrant()
    result: dict[str, Any] = {}

    if fields:
        texts = [FIELD_TEMPLATE.format(**f) for f in fields]
        vectors = encode_documents(texts)
        payloads = [
            {"table_name": f["table_name"], "field_name": f["field_name"],
             "alias": f["alias"], "field_desc": f["field_desc"]}
            for f in fields
        ]
        result["fields"] = vector_store.rebuild_collection(
            qdrant, settings.qdrant.field_collection, vectors, payloads
        )

    if metrics:
        texts = [METRIC_TEMPLATE.format(metric_name=m["metric_name"], alias_str=",".join(m["alias"]),
                                        metric_desc=m["metric_desc"], formula=m["formula"])
                 for m in metrics]
        vectors = encode_documents(texts)
        payloads = [
            {"metric_name": m["metric_name"], "alias": m["alias"],
             "formula": m["formula"], "table_name": m["table_name"]}
            for m in metrics
        ]
        result["metrics"] = vector_store.rebuild_collection(
            qdrant, settings.qdrant.metric_collection, vectors, payloads
        )

    meta_engine.dispose()
    logger.info("向量索引构建完成: {}", result)
    return result


def build_value_index() -> dict[str, Any]:
    """构建字段取值全文索引（全量重建）

    Returns:
        {"documents": 写入文档数}
    """
    settings = get_settings()
    meta_engine = create_engine(settings.mysql.url_for(settings.mysql.meta_database))
    dw_engine = create_engine(settings.mysql.url_for(settings.mysql.dw_database))

    # searchable 字段清单
    with Session(meta_engine) as session:
        rows = session.execute(
            select(MetaTable.table_name, MetaField.field_name)
            .join(MetaField, MetaField.table_id == MetaTable.id)
            .where(MetaField.searchable.is_(True))
        ).all()

    docs: list[dict] = []
    for table, field in rows:
        if not (IDENTIFIER_PATTERN.match(table) and IDENTIFIER_PATTERN.match(field)):
            logger.warning("非法标识符，跳过: {}.{}", table, field)
            continue

        sql = text(
            f"SELECT {field} AS v, COUNT(*) AS cnt FROM {table} "
            f"WHERE {field} IS NOT NULL AND {field} <> '' "
            f"GROUP BY {field} ORDER BY cnt DESC LIMIT :top_n"
        )
        with dw_engine.connect() as conn:
            values = conn.execute(sql, {"top_n": settings.es.top_values_per_field}).mappings().all()
        for row in values:
            docs.append({"table_name": table, "field_name": field, "value": str(row["v"])})

    logger.info("取值聚合完成: searchable {} 字段, 文档 {} 条", len(rows), len(docs))
    written = text_search.rebuild_index(ClientManager.get_es(), docs)

    meta_engine.dispose()
    dw_engine.dispose()
    logger.info("取值全文索引构建完成: {} 条", written)
    return {"documents": written}
