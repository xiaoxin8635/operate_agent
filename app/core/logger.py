# -*- coding: utf-8 -*-
"""
Loguru 日志模块

职责：
    1. 统一初始化控制台 + 文件双输出（文件按天滚动，保留 14 天）
    2. 提供 request_id 上下文注入能力（配合 middleware 实现并发日志追踪）
"""
import sys
from pathlib import Path

from loguru import logger

# 日志格式：时间 | 级别 | request_id | 模块:行号 | 消息
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[request_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> None:
    """初始化全局日志（应用启动时调用一次）

    Args:
        log_dir: 日志文件目录
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # 移除默认 handler，避免重复输出
    logger.remove()

    # 控制台输出（彩色）
    logger.add(
        sys.stderr,
        format=LOG_FORMAT,
        level=level,
        enqueue=True,          # 多进程/多线程安全
        backtrace=True,        # 异常时打印完整堆栈
        diagnose=True,
    )

    # 文件输出（按天滚动、保留 14 天、UTF-8 编码）
    logger.add(
        str(log_path / "app_{time:YYYY-MM-DD}.log"),
        format=LOG_FORMAT,
        level=level,
        rotation="00:00",      # 每天零点切割
        retention="14 days",   # 保留 14 天
        encoding="utf-8",
        enqueue=True,
    )

    # 为所有日志注入默认 request_id 占位（无请求上下文时显示 "-"）
    logger.configure(extra={"request_id": "-"})


def bind_request_logger(request_id: str):
    """获取绑定 request_id 的日志器上下文

    用法：
        with bind_request_logger(req_id):
            logger.info("处理中")

    Args:
        request_id: 请求唯一标识

    Returns:
        loguru contextualize 上下文管理器
    """
    return logger.contextualize(request_id=request_id)
