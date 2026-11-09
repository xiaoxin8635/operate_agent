# -*- coding: utf-8 -*-
"""
问数接口（SSE 流式）

POST /api/query：
    1. 接收自然语言问题，驱动 12 节点流水线
    2. SSE 事件流：每个节点完成推送 progress 事件 → 推送 result 事件 → [DONE]
    3. 客户端断连时 generator 被终止，graph.stream 惰性求值自动停止后续节点
       （自然取消，不再发起后续 LLM 调用与 SQL 执行）
"""
import json
from typing import Iterator, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.core.logger import logger
from app.graph.build import build_full_graph
from app.services.answer import generate_answer

router = APIRouter(prefix="/api", tags=["query"])

# 完整流水线单例（LangGraph 图不可变，进程内复用）
_graph = None


def _get_graph():
    """获取编译后的完整流水线（懒加载单例）"""
    global _graph
    if _graph is None:
        _graph = build_full_graph()
        logger.info("LangGraph 完整流水线已构建")
    return _graph


class QueryRequest(BaseModel):
    """问数请求体"""

    question: str = Field(..., min_length=2, max_length=500, description="自然语言问题")
    top_k: Optional[int] = Field(None, ge=1, le=50, description="字段召回条数覆盖（可选）")


def _sse(event: str, data: dict) -> dict:
    """构造 SSE 事件字典

    Args:
        event: 事件类型（progress / result / end）
        data: 事件数据（自动 JSON 序列化）

    Returns:
        sse-starlette 事件字典
    """
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


def _run_pipeline_events(question: str, request_id: str, top_k: Optional[int]) -> Iterator[dict]:
    """执行流水线并产出 SSE 事件（同步 generator，EventSourceResponse 自动线程化）

    Args:
        question: 用户问题
        request_id: 请求 ID（日志追踪）
        top_k: 字段召回条数覆盖

    Yields:
        SSE 事件字典
    """
    initial_state = {
        "question": question,
        "repair_count": 0,
        "node_trace": [],
    }
    # top_k 覆盖通过 configurable 传入召回节点
    run_config = {"configurable": {"request_id": request_id}}
    if top_k is not None:
        run_config["configurable"]["field_top_k"] = top_k

    final_state: dict = {}
    try:
        # stream_mode="updates"：每个节点完成产出一次增量，用于进度推送
        for chunk in _get_graph().stream(initial_state, stream_mode="updates", config=run_config):
            for node_name, updates in chunk.items():
                # 合并增量到最终状态（node_trace 为 append 语义，其余覆盖）
                for key, value in updates.items():
                    if key == "node_trace":
                        final_state.setdefault("node_trace", []).extend(value)
                    else:
                        final_state[key] = value
                brief = _node_brief(node_name, updates)
                yield _sse("progress", {"node": node_name, "status": "done", "brief": brief})
    except Exception as exc:  # noqa: BLE001 - 流水线异常转为 error 事件推送
        logger.exception("流水线执行异常: {}", exc)
        yield _sse("result", {
            "answer": "",
            "sql": "",
            "rows": [],
            "columns": [],
            "row_total": 0,
            "error": f"系统执行异常: {exc}",
            "trace": final_state.get("node_trace", []),
        })
        yield {"event": "end", "data": "[DONE]"}
        return

    # 成功路径：生成自然语言回答并推送最终结果
    error = final_state.get("error")
    answer = ""
    if error is None and final_state.get("execute_result"):
        answer = generate_answer(question, final_state["execute_result"])

    exec_result = final_state.get("execute_result", {})
    yield _sse("result", {
        "answer": answer,
        "sql": final_state.get("sql", ""),
        "columns": exec_result.get("columns", []),
        "rows": exec_result.get("rows", []),
        "row_total": exec_result.get("row_total", 0),
        "error": error,
        "repaired_rounds": final_state.get("repair_count", 0),
        "trace": final_state.get("node_trace", []),
    })
    yield {"event": "end", "data": "[DONE]"}


def _node_brief(node_name: str, updates: dict) -> str:
    """构造节点进度简报文本

    Args:
        node_name: 节点名
        updates: 节点输出增量

    Returns:
        简报（如"命中 5 个字段"）
    """
    briefs = {
        "n01_keyword_extraction": "抽取关键词",
        "n02_field_recall": f"字段召回 {len(updates.get('field_recall_results', []))} 条",
        "n03_value_recall": f"取值召回 {len(updates.get('value_recall_results', []))} 条",
        "n04_metric_recall": f"指标召回 {len(updates.get('metric_recall_results', []))} 条",
        "n05_recall_merge": "召回合并",
        "n06_table_filter": f"候选表 {len(updates.get('candidate_tables', []))} 张",
        "n07_metric_filter": f"指标过滤后 {len(updates.get('candidate_metrics', []))} 个",
        "n08_context_supplement": "上下文拼装完成",
        "n09_sql_generation": "SQL 生成" + ("完成" if updates.get("sql") else "失败"),
        "n10_sql_validate": "SQL 校验通过" if updates.get("validate_result", {}).get("passed") else "SQL 校验未通过",
        "n11_sql_repair": f"SQL 纠错（第 {updates.get('repair_count', '?')} 轮）",
        "n12_sql_execute": f"执行返回 {updates.get('execute_result', {}).get('row_total', 0)} 行",
    }
    return briefs.get(node_name, node_name)


@router.post("/query")
async def query(req: QueryRequest, request: Request) -> EventSourceResponse:
    """问数主接口：SSE 流式返回节点进度与最终结果

    Args:
        req: 请求体（问题）
        request: FastAPI 请求对象（取 request_id）

    Returns:
        SSE 事件流响应
    """
    request_id = getattr(request.state, "request_id", "-")
    logger.info("收到问数请求: {} (request_id={})", req.question, request_id)
    return EventSourceResponse(_run_pipeline_events(req.question, request_id, req.top_k))
