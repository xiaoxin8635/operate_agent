# -*- coding: utf-8 -*-
"""
FastAPI 应用入口

职责：
    1. 创建 FastAPI 实例并挂载 lifespan（客户端生命周期）
    2. 注册请求 ID 中间件（并发日志追踪）
    3. 注册路由（health / query 等）
"""
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.index_api import router as index_router
from app.api.query import router as query_router
from app.core.clients import lifespan
from app.core.config import get_settings
from app.core.logger import logger, setup_logger
from app.core.middleware import RequestIDMiddleware


def create_app() -> FastAPI:
    """创建并装配 FastAPI 应用

    Returns:
        装配完成的 FastAPI 实例
    """
    settings = get_settings()

    # 日志初始化（需在创建实例前完成，保证后续日志走统一格式）
    setup_logger(log_dir="logs", level=settings.log_level)

    app = FastAPI(
        title="经营分析 Agent",
        description="自然语言问数系统：NL -> 检索增强 -> SQL 生成/校验/纠错 -> 执行",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 中间件（注意注册顺序：后注册先执行）
    app.add_middleware(RequestIDMiddleware)

    # 路由
    app.include_router(health_router)
    app.include_router(query_router)
    app.include_router(index_router)

    logger.info("应用装配完成")
    return app


app = create_app()
