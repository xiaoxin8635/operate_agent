# -*- coding: utf-8 -*-
"""
健康检查接口

GET /api/health：探活 MySQL / Qdrant / ES 三个中间件，
返回整体状态与各组件明细，用于 M1 基础设施验收与运维探活。
"""
from fastapi import APIRouter

from app.core.clients import check_es, check_mysql, check_qdrant
from app.core.logger import logger

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict:
    """健康检查：探活全部中间件

    Returns:
        {
          "status": "ok" | "degraded",
          "components": {"mysql": "ok", "qdrant": "ok", "elasticsearch": "ok"}
        }
        status 为 ok 当且仅当全部组件 ok，否则 degraded。
    """
    components = {
        "mysql": check_mysql(),
        "qdrant": check_qdrant(),
        "elasticsearch": check_es(),
    }
    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    logger.info("健康检查完成: status={} components={}", status, components)
    return {"status": status, "components": components}
