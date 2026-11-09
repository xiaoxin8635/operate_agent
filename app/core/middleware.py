# -*- coding: utf-8 -*-
"""
请求 ID 中间件

职责：为每个 HTTP 请求生成唯一 request_id，注入日志上下文与响应头，
解决并发场景下日志无法区分请求的追踪问题。
"""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logger import bind_request_logger

# 请求 ID 透传头名称（网关/上游可传入实现全链路追踪）
REQUEST_ID_HEADER = "X-Request-Id"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件：解析/生成 request_id 并贯穿日志与响应"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 优先复用上游传入的 request_id（便于跨服务追踪），否则本地生成短码
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        # 该请求处理期间的所有日志自动携带 request_id
        with bind_request_logger(request_id):
            response = await call_next(request)

        # 响应头回传 request_id，便于前端/调用方排障
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
