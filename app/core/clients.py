# -*- coding: utf-8 -*-
"""
外部客户端生命周期管理

职责：
    1. FastAPI lifespan 统一初始化 / 销毁全部外部客户端（MySQL、Qdrant、ES）
    2. BGE Embedding 模型懒加载（首次调用才加载，避免启动即下载模型）
    3. 全局单例访问入口，避免每请求重复建连

注意：本模块持有的是有状态资源，任何业务代码禁止自行 create_engine /
新建 QdrantClient / Elasticsearch，统一从 ClientManager 获取。
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from elasticsearch import Elasticsearch
from fastapi import FastAPI
from qdrant_client import QdrantClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from app.core.config import get_settings
from app.core.logger import logger


class ClientManager:
    """外部客户端单例管理器（进程级唯一）"""

    _engine: Optional[Engine] = None       # MySQL SQLAlchemy 引擎（含连接池）
    _qdrant: Optional[QdrantClient] = None  # Qdrant 向量库客户端
    _es: Optional[Elasticsearch] = None     # Elasticsearch 客户端
    _embedding_model = None                 # BGE 模型（懒加载，不参与 init/close）

    # ------------------------------------------------------------------
    # 初始化 / 销毁
    # ------------------------------------------------------------------
    @classmethod
    def init(cls) -> None:
        """初始化所有外部客户端（lifespan startup 阶段调用）"""
        settings = get_settings()

        # MySQL：PyMySQL 驱动 + 连接池（预 ping 防止 MySQL 8 长连接断开）
        db_url = (
            f"mysql+pymysql://{settings.mysql.user}:{settings.mysql.password}"
            f"@{settings.mysql.host}:{settings.mysql.port}/?charset=utf8mb4"
        )
        cls._engine = create_engine(
            db_url,
            pool_size=settings.mysql.pool_size,
            pool_recycle=settings.mysql.pool_recycle,
            pool_pre_ping=True,
            poolclass=QueuePool,
        )
        logger.info("MySQL 引擎初始化完成: {}:{}", settings.mysql.host, settings.mysql.port)

        # Qdrant
        cls._qdrant = QdrantClient(url=settings.qdrant.url, timeout=10)
        logger.info("Qdrant 客户端初始化完成: {}", settings.qdrant.url)

        # Elasticsearch
        cls._es = Elasticsearch(settings.es.host, request_timeout=10)
        logger.info("Elasticsearch 客户端初始化完成: {}", settings.es.host)

    @classmethod
    def close(cls) -> None:
        """销毁所有客户端（lifespan shutdown 阶段调用）"""
        if cls._engine is not None:
            cls._engine.dispose()
            cls._engine = None
            logger.info("MySQL 引擎已关闭")
        if cls._qdrant is not None:
            cls._qdrant.close()
            cls._qdrant = None
            logger.info("Qdrant 客户端已关闭")
        if cls._es is not None:
            cls._es.close()
            cls._es = None
            logger.info("Elasticsearch 客户端已关闭")

    # ------------------------------------------------------------------
    # 单例访问
    # ------------------------------------------------------------------
    @classmethod
    def get_engine(cls) -> Engine:
        """获取 MySQL SQLAlchemy 引擎（未初始化时抛错）"""
        if cls._engine is None:
            raise RuntimeError("MySQL 引擎未初始化，请确认应用经 lifespan 启动")
        return cls._engine

    @classmethod
    def get_qdrant(cls) -> QdrantClient:
        """获取 Qdrant 客户端单例"""
        if cls._qdrant is None:
            raise RuntimeError("Qdrant 客户端未初始化，请确认应用经 lifespan 启动")
        return cls._qdrant

    @classmethod
    def get_es(cls) -> Elasticsearch:
        """获取 Elasticsearch 客户端单例"""
        if cls._es is None:
            raise RuntimeError("Elasticsearch 客户端未初始化，请确认应用经 lifespan 启动")
        return cls._es

    @classmethod
    def get_embedding_model(cls):
        """获取 BGE Embedding 模型（懒加载：首次调用时下载/加载模型）

        Returns:
            SentenceTransformer 实例
        """
        if cls._embedding_model is None:
            from sentence_transformers import SentenceTransformer  # 延迟导入，避免启动加载 torch

            settings = get_settings()
            logger.info("开始加载 BGE 模型: {} (首次加载会下载模型)", settings.embedding.model_name)
            cls._embedding_model = SentenceTransformer(
                settings.embedding.model_name,
                device=settings.embedding.device,
                cache_folder=settings.embedding.cache_dir,
            )
            logger.info("BGE 模型加载完成")
        return cls._embedding_model


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI 生命周期钩子：启动时初始化客户端，关闭时销毁

    Args:
        app: FastAPI 应用实例
    """
    logger.info("应用启动：初始化外部客户端...")
    ClientManager.init()
    yield
    logger.info("应用关闭：销毁外部客户端...")
    ClientManager.close()


# ----------------------------------------------------------------------
# 供 health 接口使用的连通性检查（返回 ok / error 状态，不抛异常）
# ----------------------------------------------------------------------
def check_mysql() -> str:
    """检查 MySQL 连通性（SELECT 1 探活）"""
    try:
        with ClientManager.get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - 健康检查需捕获一切异常转为状态
        logger.warning("MySQL 健康检查失败: {}", exc)
        return f"error: {exc}"


def check_qdrant() -> str:
    """检查 Qdrant 连通性（列举集合探活）"""
    try:
        ClientManager.get_qdrant().get_collections()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant 健康检查失败: {}", exc)
        return f"error: {exc}"


def check_es() -> str:
    """检查 Elasticsearch 连通性（ping 探活）"""
    try:
        ok = ClientManager.get_es().ping()
        return "ok" if ok else "error: ping returned False"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Elasticsearch 健康检查失败: {}", exc)
        return f"error: {exc}"
