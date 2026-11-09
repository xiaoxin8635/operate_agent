# -*- coding: utf-8 -*-
"""
节点 12：SQL 执行

职责：
    1. 只读事务兜底：执行前 SET TRANSACTION READ ONLY，即使校验被绕过，
       数据库层也会拒绝写操作（双保险）
    2. 执行并截断结果行数（result_row_limit）
    3. 执行异常转 error 字段，由条件边路由进纠错或终止
"""
from sqlalchemy import text

from app.core.config import get_settings
from app.core.logger import logger
from app.core.clients import ClientManager


def n12_sql_execute(state: dict) -> dict:
    """节点 12 入口：只读执行 SQL

    Args:
        state: 全局状态（需含 sql）

    Returns:
        状态增量 {execute_result, error, node_trace}
    """
    settings = get_settings()
    sql = state["sql"]
    logger.info("节点12 SQL执行开始")

    engine = ClientManager.get_engine()
    try:
        with engine.connect() as conn:
            # SET TRANSACTION 只对"下一个事务"生效；SQLAlchemy autobegin 下该语句
            # 自身会开启事务，故先提交空事务，使随后的 SELECT 落入只读事务
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.commit()
            result = conn.execute(text(sql))   # 开启只读事务，写操作将被 MySQL 拒绝
            rows = result.fetchall()
            columns = list(result.keys())
            conn.commit()   # 结束只读事务（SELECT 无写副作用，仅归还连接）

        # 行数截断（防止大结果拖垮响应）
        row_total = len(rows)
        rows_limited = rows[: settings.graph.result_row_limit]
        # Decimal/datetime 等类型转字符串，保证 JSON 可序列化
        serialized = [[str(v) if not isinstance(v, (int, float, str, type(None))) else v for v in row]
                      for row in rows_limited]

        logger.info("节点12 完成: {} 行 (返回 {} 行)", row_total, len(serialized))
        return {
            "execute_result": {"columns": columns, "rows": serialized, "row_total": row_total},
            "error": None,
            "node_trace": [{"node": "n12_sql_execute", "status": "done", "rows": row_total}],
        }
    except Exception as exc:  # noqa: BLE001 - 执行异常转纠错/终止路由
        logger.error("节点12 执行失败: {}", exc)
        return {
            "execute_result": {"columns": [], "rows": [], "row_total": 0},
            "error": f"SQL 执行失败: {exc}",
            "node_trace": [{"node": "n12_sql_execute", "status": "failed"}],
        }
