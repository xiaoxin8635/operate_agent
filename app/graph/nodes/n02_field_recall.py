# -*- coding: utf-8 -*-
"""
节点 2：字段向量召回

职责：用户问题 → BGE 查询向量 → Qdrant field_index 相似检索，
得到语义相关的候选字段（如"销售额"匹配到 pay_amount 字段）。
支持通过 configurable.field_top_k 覆盖默认召回条数（API 请求参数）。
"""
from typing import Optional

from langchain_core.runnables import RunnableConfig

from app.core.clients import ClientManager
from app.core.config import get_settings
from app.core.logger import logger
from app.services.embedding import encode_query
from app.services.vector_store import search_fields


def n02_field_recall(state: dict, config: Optional[RunnableConfig] = None) -> dict:
    """节点 2 入口：字段向量召回

    Args:
        state: 全局状态（需含 question）
        config: LangGraph 运行配置（可含 configurable.field_top_k 覆盖）

    Returns:
        状态增量 {field_recall_results, node_trace}
    """
    question = state["question"]
    settings = get_settings()
    top_k = settings.recall.field_top_k
    if config and config.get("configurable", {}).get("field_top_k"):
        top_k = int(config["configurable"]["field_top_k"])
    logger.info("节点2 字段向量召回开始 (top_k={})", top_k)

    query_vector = encode_query(question)
    results = search_fields(
        ClientManager.get_qdrant(),
        query_vector,
        top_k=top_k,
        score_threshold=settings.recall.field_score_threshold,
    )

    logger.info("节点2 完成: 命中 {} 个字段", len(results))
    return {
        "field_recall_results": results,
        "node_trace": [{"node": "n02_field_recall", "status": "done", "hits": len(results)}],
    }
