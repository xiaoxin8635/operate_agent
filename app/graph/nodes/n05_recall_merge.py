# -*- coding: utf-8 -*-
"""
节点 5：召回信息合并

职责：合并三路召回结果：
    1. 字段向量召回结果直接进入候选字段
    2. 取值召回命中的字段并入候选字段（携带 matched_value 证据，供 Prompt 注入）
    3. 同一 (table_name, field_name) 去重，取最高分并合并证据
"""
from app.core.logger import logger


def n05_recall_merge(state: dict) -> dict:
    """节点 5 入口：合并字段/取值/指标三路召回

    Args:
        state: 全局状态（需含三个召回结果 key）

    Returns:
        状态增量 {candidate_fields, candidate_metrics, node_trace}
    """
    field_results = state.get("field_recall_results", [])
    value_results = state.get("value_recall_results", [])
    metric_results = state.get("metric_recall_results", [])
    logger.info("节点5 召回合并开始: 字段 {} 取值 {} 指标 {}", len(field_results), len(value_results), len(metric_results))

    # 以 (table_name, field_name) 为键合并字段
    merged: dict[tuple[str, str], dict] = {}
    for item in field_results:
        key = (item["table_name"], item["field_name"])
        merged[key] = {
            "table_name": item["table_name"],
            "field_name": item["field_name"],
            "alias": item.get("alias"),
            "field_desc": item.get("field_desc"),
            "score": item.get("score", 0.0),
            "matched_values": [],       # 取值证据（来自节点 3）
            "source": "vector",         # 召回来源
        }

    for item in value_results:
        key = (item["table_name"], item["field_name"])
        if key in merged:
            merged[key]["matched_values"].append(item["value"])
            merged[key]["score"] = max(merged[key]["score"], item["score"])
        else:
            # 值召回独有命中的字段（如问"完美日记销量"但向量未召回 brand）
            merged[key] = {
                "table_name": item["table_name"],
                "field_name": item["field_name"],
                "alias": None,
                "field_desc": None,
                "score": item.get("score", 0.0),
                "matched_values": [item["value"]],
                "source": "value_match",
            }

    candidate_fields = sorted(merged.values(), key=lambda x: -x["score"])
    logger.info("节点5 完成: 合并后候选字段 {} 个（值证据字段 {} 个）",
                len(candidate_fields),
                sum(1 for f in candidate_fields if f["matched_values"]))

    return {
        "candidate_fields": candidate_fields,
        "candidate_metrics": metric_results,   # 指标在节点 7 进一步过滤
        "node_trace": [{"node": "n05_recall_merge", "status": "done", "fields": len(candidate_fields)}],
    }
