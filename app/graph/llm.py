# -*- coding: utf-8 -*-
"""
LLM 客户端封装

职责：
    1. 基于 langchain-openai 创建 DeepSeek 聊天模型实例（OpenAI 兼容接口）
    2. 提供统一的调用入口（含日志记录耗时与摘要）
"""
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.logger import logger


def get_llm(temperature: float | None = None) -> ChatOpenAI:
    """获取 DeepSeek 聊天模型实例（配置来源于 app_settings.yaml 与 .env）

    Args:
        temperature: 覆盖默认温度（None 则用配置值）

    Returns:
        ChatOpenAI 实例
    """
    settings = get_settings()
    return ChatOpenAI(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature if temperature is None else temperature,
        max_tokens=settings.llm.max_tokens,
        timeout=settings.llm.timeout,
    )


def invoke_llm(prompt: str, purpose: str, temperature: float | None = None) -> str:
    """调用 LLM 并记录日志（单次调用封装）

    Args:
        prompt: 完整 Prompt 文本
        purpose: 调用用途（日志标识，如 keyword_extraction / sql_generation）
        temperature: 覆盖默认温度

    Returns:
        模型响应文本

    Raises:
        Exception: LLM 调用失败时原样抛出（由调用节点决定兜底策略）
    """
    llm = get_llm(temperature)
    logger.info("LLM 调用开始: {} (prompt {} 字符)", purpose, len(prompt))
    response = llm.invoke(prompt)
    content = response.content
    logger.info("LLM 调用完成: {} (响应 {} 字符)", purpose, len(content))
    return content
