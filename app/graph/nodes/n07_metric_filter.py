# -*- coding: utf-8 -*-
"""
节点 7：指标过滤

职责：
    1. 别名精确命中增强：问题或 LLM 抽取的指标词与指标别名完全匹配时强制保留
       （向量召回得分高不代表精确命中，字符串匹配作为置信度补充）
    2. 从 Meta MySQL 反查指标的关联字段（Qdrant payload 不存该信息，元数据以 MySQL 为唯一来源），
       确保候选字段集不遗漏指标字段
"""
from sqlalchemy import select

from app.core.clients import ClientManager
from app.core.logger import logger
from app.models.meta import MetaMetric


def _load_related_fields(metric_names: list[str]) -> dict[str, dict]:
    """从 Meta MySQL 反查指标的公式与关联字段

    Args:
        metric_names: 指标名列表

    Returns:
        {metric_name: {formula, table_name, related_fields}}
    """
    if not metric_names:
        return {}
    with ClientManager.get_engine().connect() as conn:
        rows = conn.execute(
            select(MetaMetric.metric_name, MetaMetric.formula, MetaMetric.table_name, MetaMetric.related_fields)
            .where(MetaMetric.metric_name.in_(metric_names))
        ).mappings().all()
    return {
        r["metric_name"]: {
            "formula": r["formula"],
            "table_name": r["table_name"],
            "related_fields": r["related_fields"] or [],
        }
        for r in rows
    }


def n07_metric_filter(state: dict) -> dict:
    """节点 7 入口：指标过滤与关联字段补全

    Args:
        state: 全局状态（需含 candidate_metrics / keywords / candidate_fields）

    Returns:
        状态增量 {candidate_metrics, candidate_fields, node_trace}
    """
    candidate_metrics = state.get("candidate_metrics", [])
    keywords = state.get("keywords", {})
    candidate_fields = state.get("candidate_fields", [])
    logger.info("节点7 指标过滤开始: 待过滤指标 {} 个", len(candidate_metrics))

    # 问题与 LLM 抽取的指标词合并为匹配文本（小写比较）
    match_texts = " ".join([state["question"]] + keywords.get("metric_words", [])).lower()

    # 别名精确命中（问题中包含任一别名）→ 强制保留并置满分
    filtered: list[dict] = []
    for metric in candidate_metrics:
        alias_list = metric.get("alias") or []
        exact_hit = any(alias.lower() in match_texts for alias in alias_list if alias)
        item = {**metric, "exact_hit": exact_hit}
        if exact_hit:
            item["score"] = 1.0
        filtered.append(item)

    # 过滤策略：精确命中的全保留；未精确命中的仅保留向量得分最高的一个（语义相关兜底）
    exact_items = [m for m in filtered if m["exact_hit"]]
    final_metrics = exact_items if exact_items else (filtered[:1] if filtered else [])

    # 从元数据反查关联字段并补入候选字段集（保证 SQL 生成时字段不遗漏）
    meta_map = _load_related_fields([m["metric_name"] for m in final_metrics])
    existing_keys = {(f["table_name"], f["field_name"]) for f in candidate_fields}
    added_fields: list[dict] = []
    for metric in final_metrics:
        meta = meta_map.get(metric["metric_name"], {})
        metric["formula"] = meta.get("formula", metric.get("formula"))
        for field_name in meta.get("related_fields", []):
            key = (metric["table_name"], field_name)
            if key not in existing_keys:
                existing_keys.add(key)
                added_fields.append({
                    "table_name": metric["table_name"],
                    "field_name": field_name,
                    "alias": None,
                    "field_desc": f"指标 {metric['metric_name']} 关联字段",
                    "score": 0.5,
                    "matched_values": [],
                    "source": "metric_related",
                })
    candidate_fields = candidate_fields + added_fields

    logger.info("节点7 完成: 保留指标 {} 个，补入关联字段 {} 个",
                [m["metric_name"] for m in final_metrics], len(added_fields))
    return {
        "candidate_metrics": final_metrics,
        "candidate_fields": candidate_fields,
        "node_trace": [{"node": "n07_metric_filter", "status": "done", "metrics": len(final_metrics)}],
    }
