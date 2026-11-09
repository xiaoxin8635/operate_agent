# -*- coding: utf-8 -*-
"""
节点 3：字段值召回（ES 全文）

职责：问题中的实体词 → ES field_value_index 全文检索，
定位实体所属字段（如"完美日记" → dw_orders.brand）。
实体词为空时回退用问题原文检索（ES match 自带分词兜底）。
"""
from app.core.clients import ClientManager
from app.core.config import get_settings
from app.core.logger import logger
from app.services.text_search import search_values


def n03_value_recall(state: dict) -> dict:
    """节点 3 入口：字段值全文召回

    Args:
        state: 全局状态（需含 question 与 keywords）

    Returns:
        状态增量 {value_recall_results, node_trace}
    """
    question = state["question"]
    entities = state.get("keywords", {}).get("entities", [])
    settings = get_settings()
    es = ClientManager.get_es()

    # 实体词逐个检索；无实体时用原文兜底（ES match 会自行分词匹配）
    terms = entities if entities else [question]
    logger.info("节点3 字段值召回开始: terms={}", terms)

    results: list[dict] = []
    seen = set()
    for term in terms:
        hits = search_values(es, term, size=settings.recall.es_size)
        for hit in hits:
            # 同一 (table, field, value) 去重
            key = (hit["table_name"], hit["field_name"], hit["value"])
            if key in seen:
                continue
            seen.add(key)
            results.append(hit)

    logger.info("节点3 完成: 命中 {} 个取值", len(results))
    return {
        "value_recall_results": results,
        "node_trace": [{"node": "n03_value_recall", "status": "done", "hits": len(results)}],
    }
