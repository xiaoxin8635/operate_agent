# -*- coding: utf-8 -*-
"""
索引管理接口

POST /api/index/rebuild：触发向量索引（Qdrant）与取值全文索引（ES）全量重建。
管理用途接口，本期不加鉴权（需求范围外），部署时应在网关层限制访问。
"""
from fastapi import APIRouter

from app.core.clients import ClientManager
from app.core.logger import logger
from app.services.index_builder import build_value_index, build_vector_index

router = APIRouter(prefix="/api", tags=["index"])


@router.post("/index/rebuild")
async def rebuild_index() -> dict:
    """全量重建向量索引与取值索引（同步执行）

    Returns:
        {"status": "ok", "vector": {...}, "value": {...}} 或
        {"status": "error", "message": ...}
    """
    logger.info("收到索引重建请求")
    # 冷启动防御：应用经 lifespan 启动时已初始化；此处兜底避免未初始化调用报错
    if ClientManager._engine is None:  # noqa: SLF001
        ClientManager.init()

    try:
        vector_result = build_vector_index()
        value_result = build_value_index()
        return {"status": "ok", "vector": vector_result, "value": value_result}
    except Exception as exc:  # noqa: BLE001 - 管理接口将异常转为可读响应
        logger.exception("索引重建失败: {}", exc)
        return {"status": "error", "message": str(exc)}


@router.get("/index/rebuild")
async def rebuild_index_hint() -> dict:
    """防误用提示：索引重建必须使用 POST"""
    return {"hint": "请使用 POST /api/index/rebuild 触发索引重建"}
