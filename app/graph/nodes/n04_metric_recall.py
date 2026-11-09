# -*- coding: utf-8 -*-
"""
节点 4：指标向量召回

职责：用户问题 → BGE 查询向量 → Qdrant metric_index 相似检索，
命中业务指标口径（如"销售额" → GMV 指标定义）。
"""
from app.core.clients import ClientManager
from app.core.config import get_settings
from app.core.logger import logger
from app.services.embedding import encode_query
from app.services.vector_store import search_metrics


def n04_metric_recall(state: dict) -> dict:
    """节点 4 入口：指标向量召回

    Args:
        state: 全局状态（需含 question）

    Returns:
        状态增量 {metric_recall_results, node_trace}
    """
    question = state["question"]
    settings = get_settings()
    logger.info("节点4 指标向量召回开始")

    query_vector = encode_query(question)
    results = search_metrics(
        ClientManager.get_qdrant(),
        query_vector,
        top_k=settings.recall.metric_top_k,
        score_threshold=settings.recall.metric_score_threshold,
    )

    logger.info("节点4 完成: 命中 {} 个指标", len(results))
    return {
        "metric_recall_results": results,
        "node_trace": [{"node": "n04_metric_recall", "status": "done", "hits": len(results)}],
    }
