# -*- coding: utf-8 -*-
"""
自然语言回答生成服务

职责：SQL 执行成功后，基于查询结果由 LLM 生成面向用户的自然语言回答
（配置开关 graph.enable_answer_summary，关闭时返回空串）。
"""
import json

from app.core.config import get_settings
from app.core.logger import logger
from app.graph.llm import invoke_llm

ANSWER_PROMPT_TEMPLATE = """你是电商数据分析助手。根据用户问题和 SQL 查询结果，用简洁的中文回答用户。

【用户问题】
{question}

【查询结果】（JSON，columns 为列名，rows 为数据行，最多展示 10 行）
{result_json}

要求：
1. 直接给出数值结论，数字保留合理精度；
2. 结果为空时说明该条件下没有数据；
3. 多行数据时给出关键概括，可列出前几名的对比；
4. 只输出回答文本，不要输出 SQL 或分析过程。"""


def generate_answer(question: str, execute_result: dict) -> str:
    """基于执行结果生成自然语言回答

    Args:
        question: 用户问题
        execute_result: 节点 12 输出 {columns, rows, row_total}

    Returns:
        回答文本；配置关闭或生成失败时返回空串（前端回退展示原始行数据）
    """
    settings = get_settings()
    if not settings.graph.enable_answer_summary:
        return ""

    # 结果过大时仅截取前 10 行送 LLM（控制 token）
    preview = {
        "columns": execute_result.get("columns", []),
        "rows": execute_result.get("rows", [])[:10],
        "row_total": execute_result.get("row_total", 0),
    }
    prompt = ANSWER_PROMPT_TEMPLATE.format(question=question, result_json=json.dumps(preview, ensure_ascii=False))
    try:
        answer = invoke_llm(prompt, purpose="answer_summary", temperature=0.3)
        return answer.strip()
    except Exception as exc:  # noqa: BLE001 - 回答生成失败不影响主流程
        logger.warning("自然语言回答生成失败: {}", exc)
        return ""
