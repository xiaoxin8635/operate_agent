# -*- coding: utf-8 -*-
"""
Qdrant 向量库服务

职责：
    1. 集合管理：幂等创建 field_index / metric_index 两个集合（512 维 Cosine）
    2. 全量重建：删除集合重建并批量写入向量点（构建脚本使用）
    3. 相似检索：字段检索 / 指标检索（LangGraph 召回节点使用）

payload 约定：
    - field_index:  {table_name, field_name, alias, field_desc}
    - metric_index: {metric_name, alias, formula, table_name}
"""
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.core.config import get_settings
from app.core.logger import logger


def ensure_collections(client: QdrantClient) -> None:
    """幂等创建两个向量集合（已存在则跳过）

    Args:
        client: Qdrant 客户端
    """
    settings = get_settings()
    existing = {c.name for c in client.get_collections().collections}

    for name in (settings.qdrant.field_collection, settings.qdrant.metric_collection):
        if name in existing:
            logger.info("Qdrant 集合已存在，跳过创建: {}", name)
            continue
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=512, distance=Distance.COSINE),
        )
        logger.info("Qdrant 集合创建完成: {}", name)


def rebuild_collection(
    client: QdrantClient,
    collection_name: str,
    vectors: list[list[float]],
    payloads: list[dict[str, Any]],
) -> int:
    """全量重建集合：删除 → 重建 → 批量写入

    Args:
        client: Qdrant 客户端
        collection_name: 集合名
        vectors: 向量列表（与 payloads 一一对应）
        payloads: payload 字典列表

    Returns:
        写入的点数
    """
    if len(vectors) != len(payloads):
        raise ValueError(f"向量数 {len(vectors)} 与 payload 数 {len(payloads)} 不一致")

    settings = get_settings()
    client.delete_collection(collection_name)
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=512, distance=Distance.COSINE),
    )

    # 分批 upsert（Qdrant 单次建议不超过几千点）
    batch_size = 500
    for i in range(0, len(vectors), batch_size):
        points = [
            PointStruct(id=i + j, vector=vector, payload=payload)
            for j, (vector, payload) in enumerate(zip(vectors[i:i + batch_size], payloads[i:i + batch_size]))
        ]
        client.upsert(collection_name=collection_name, points=points)

    logger.info("Qdrant 集合重建完成: {} ({} 点)", collection_name, len(vectors))
    return len(vectors)


def search_fields(
    client: QdrantClient,
    query_vector: list[float],
    top_k: int,
    score_threshold: float,
) -> list[dict[str, Any]]:
    """字段语义检索：问题向量 → 相关字段

    Args:
        client: Qdrant 客户端
        query_vector: 归一化查询向量
        top_k: 返回条数
        score_threshold: 相似度得分阈值（低于丢弃）

    Returns:
        [{"table_name", "field_name", "alias", "field_desc", "score"}, ...] 按得分降序
    """
    settings = get_settings()
    hits = client.query_points(
        collection_name=settings.qdrant.field_collection,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    ).points

    results = []
    for hit in hits:
        if hit.score < score_threshold:
            continue
        payload = hit.payload or {}
        results.append({
            "table_name": payload.get("table_name"),
            "field_name": payload.get("field_name"),
            "alias": payload.get("alias"),
            "field_desc": payload.get("field_desc"),
            "score": round(hit.score, 4),
        })
    return results


def search_metrics(
    client: QdrantClient,
    query_vector: list[float],
    top_k: int,
    score_threshold: float,
) -> list[dict[str, Any]]:
    """指标语义检索：问题向量 → 相关指标

    Args:
        client: Qdrant 客户端
        query_vector: 归一化查询向量
        top_k: 返回条数
        score_threshold: 相似度得分阈值（低于丢弃）

    Returns:
        [{"metric_name", "alias", "formula", "table_name", "score"}, ...] 按得分降序
    """
    settings = get_settings()
    hits = client.query_points(
        collection_name=settings.qdrant.metric_collection,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    ).points

    results = []
    for hit in hits:
        if hit.score < score_threshold:
            continue
        payload = hit.payload or {}
        results.append({
            "metric_name": payload.get("metric_name"),
            "alias": payload.get("alias"),
            "formula": payload.get("formula"),
            "table_name": payload.get("table_name"),
            "score": round(hit.score, 4),
        })
    return results
