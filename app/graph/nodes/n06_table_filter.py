# -*- coding: utf-8 -*-
"""
节点 6：表过滤

职责：
    1. 从候选字段与指标关联表推导候选表集
    2. 同主题分层去重：同一主题（表名去掉分层前缀）同时存在 ods/dw/dm 时，
       按优先级 dm > dw > ods 只保留一层（模拟数仓每主题仅一层，规则保留兜底）
    3. 从元数据库补全候选表的别名与描述
"""
from sqlalchemy import select

from app.core.clients import ClientManager
from app.core.logger import logger
from app.models.meta import MetaTable

# 数仓分层优先级：数字越大越优先保留
LAYER_PRIORITY = {"dm": 3, "dw": 2, "ods": 1}


def _table_topic(table_name: str) -> str:
    """提取表的主题名（去掉分层前缀，如 dw_orders → orders）

    Args:
        table_name: 物理表名

    Returns:
        主题名（无前缀时返回原表名）
    """
    for prefix in ("ods_", "dwd_", "dw_", "dm_", "ads_"):
        if table_name.startswith(prefix):
            return table_name[len(prefix):]
    return table_name


def _dedupe_by_topic(table_names: list[str]) -> set[str]:
    """同主题分层去重：每主题按 LAYER_PRIORITY 保留一层

    Args:
        table_names: 候选表名列表

    Returns:
        过滤后的表名集合
    """
    topic_best: dict[str, tuple[int, str]] = {}
    for name in table_names:
        topic = _table_topic(name)
        priority = LAYER_PRIORITY.get(name.split("_", 1)[0], 0)
        best = topic_best.get(topic)
        if best is None or priority > best[0]:
            topic_best[topic] = (priority, name)
    return {name for _, name in topic_best.values()}


def n06_table_filter(state: dict) -> dict:
    """节点 6 入口：推导候选表集并补全元数据

    Args:
        state: 全局状态（需含 candidate_fields 与 candidate_metrics）

    Returns:
        状态增量 {candidate_tables, node_trace}
    """
    candidate_fields = state.get("candidate_fields", [])
    candidate_metrics = state.get("candidate_metrics", [])
    logger.info("节点6 表过滤开始: 候选字段来自 {} 表", len({f["table_name"] for f in candidate_fields}))

    # 字段所在表 + 指标关联表 全部进入候选
    table_names = {f["table_name"] for f in candidate_fields if f["table_name"]}
    table_names |= {m["table_name"] for m in candidate_metrics if m.get("table_name")}

    # 同主题分层去重
    filtered_names = _dedupe_by_topic(sorted(table_names))

    # 从元数据库补全表别名/描述（供节点 8 拼装上下文）
    tables: list[dict] = []
    if filtered_names:
        with ClientManager.get_engine().connect() as conn:
            rows = conn.execute(
                select(MetaTable.table_name, MetaTable.alias, MetaTable.table_desc, MetaTable.layer)
                .where(MetaTable.table_name.in_(filtered_names))
            ).mappings().all()
        tables = [
            {"table_name": r["table_name"], "alias": r["alias"],
             "table_desc": r["table_desc"], "layer": r["layer"]}
            for r in rows
        ]

    logger.info("节点6 完成: 候选表 {}", [t["table_name"] for t in tables])
    return {
        "candidate_tables": tables,
        "node_trace": [{"node": "n06_table_filter", "status": "done", "tables": len(tables)}],
    }
