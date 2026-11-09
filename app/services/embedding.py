# -*- coding: utf-8 -*-
"""
BGE Embedding 服务

职责：
    1. 封装 BGE(bge-small-zh-v1.5) 模型的文档向量与查询向量生成
    2. 文档侧与查询侧使用不同编码策略（BGE 官方要求查询侧加检索指令前缀）
    3. 向量统一 L2 归一化（配合 Qdrant Cosine 距离使用）
"""
from typing import Optional

from app.core.clients import ClientManager
from app.core.config import get_settings
from app.core.logger import logger

# BGE 中文模型检索场景的查询指令前缀（官方推荐，仅查询侧使用）
DEFAULT_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def encode_documents(texts: list[str]) -> list[list[float]]:
    """生成文档侧向量（元数据构建时使用，不加指令前缀）

    Args:
        texts: 文本列表（字段描述/指标描述拼接结果）

    Returns:
        归一化后的向量列表，与输入顺序一一对应
    """
    if not texts:
        return []
    model = ClientManager.get_embedding_model()
    vectors = model.encode(
        texts,
        batch_size=get_settings().embedding.batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    logger.debug("文档向量化完成: {} 条", len(texts))
    return vectors.tolist()


def encode_query(text: str, instruction: Optional[str] = None) -> list[float]:
    """生成查询侧向量（用户问题召回时使用，加检索指令前缀）

    Args:
        text: 用户问题原文
        instruction: 检索指令前缀（默认使用 BGE 官方推荐指令）

    Returns:
        归一化后的查询单向量
    """
    model = ClientManager.get_embedding_model()
    prefix = instruction if instruction is not None else DEFAULT_QUERY_INSTRUCTION
    vector = model.encode(
        prefix + text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vector.tolist()
