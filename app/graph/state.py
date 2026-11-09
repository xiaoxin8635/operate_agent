# -*- coding: utf-8 -*-
"""
LangGraph 全局状态定义

设计要点：
    1. 节点 2/3/4 并行执行，各自写独立 key（field_recall_results 等），
       避免并行写同一 key 引发 LangGraph InvalidUpdateError
    2. node_trace 由所有节点追加，使用 operator.add reducer 合并并行写入
    3. M5 节点（SQL 生成/校验/纠错/执行）相关字段在本 State 中一并声明
"""
import operator
from typing import Annotated, Optional

from typing_extensions import TypedDict


class GraphState(TypedDict, total=False):
    """12 节点流水线的全局状态（各字段含义见注释）"""

    # ---------- 输入 ----------
    question: str                    # 用户自然语言问题

    # ---------- 节点 1：关键词抽取 ----------
    keywords: dict                   # {entities, metric_words, dims}
    date_context: dict               # {expr, start, end} 规则解析的时间区间

    # ---------- 节点 2/3/4：三路并行召回（各自独立 key） ----------
    field_recall_results: list[dict]    # 字段向量召回 [{table_name, field_name, alias, field_desc, score}]
    value_recall_results: list[dict]    # 取值全文召回 [{table_name, field_name, value, score}]
    metric_recall_results: list[dict]   # 指标向量召回 [{metric_name, alias, formula, table_name, score}]

    # ---------- 节点 5/6/7/8：合并与过滤 ----------
    candidate_fields: list[dict]        # 合并后的候选字段（含来源与取值证据）
    candidate_metrics: list[dict]       # 过滤后的候选指标
    candidate_tables: list[dict]        # 候选表 [{table_name, alias, table_desc, layer}]
    schema_context: str                 # 拼装完成的 SQL 生成上下文

    # ---------- 节点 9~12：SQL 闭环（M5 实现） ----------
    sql: str                            # 生成的 SQL
    validate_result: dict               # {passed: bool, errors: [str]}
    execute_result: dict                # {columns, rows, row_total}
    answer: str                         # LLM 生成的自然语言回答

    # ---------- 闭环控制 ----------
    repair_count: int                   # 已纠错轮数
    error: Optional[str]                # 最终错误信息（成功时为 None）

    # ---------- 可观测 ----------
    node_trace: Annotated[list[dict], operator.add]   # 节点轨迹（reducer 合并并行追加）
