# -*- coding: utf-8 -*-
"""
LangGraph 流水线构图

职责：
    1. 召回图（节点 1-8）：n01 → [n02 ‖ n03 ‖ n04] 并行 → n05 → n06 → n07 → n08
    2. 完整图（节点 1-12）：召回图 → SQL 生成 → 校验 →（条件边）→ 执行 /
       纠错回环 → END
    3. 条件边路由：校验通过→执行；失败且未超纠错上限→纠错回环；否则终止

并行写安全：n02/n03/n04 各写独立 state key，node_trace 走 operator.add reducer。
"""
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.graph.nodes.n01_keyword_extraction import n01_keyword_extraction
from app.graph.nodes.n02_field_recall import n02_field_recall
from app.graph.nodes.n03_value_recall import n03_value_recall
from app.graph.nodes.n04_metric_recall import n04_metric_recall
from app.graph.nodes.n05_recall_merge import n05_recall_merge
from app.graph.nodes.n06_table_filter import n06_table_filter
from app.graph.nodes.n07_metric_filter import n07_metric_filter
from app.graph.nodes.n08_context_supplement import n08_context_supplement
from app.graph.nodes.n09_sql_generation import n09_sql_generation
from app.graph.nodes.n10_sql_validate import n10_sql_validate
from app.graph.nodes.n11_sql_repair import n11_sql_repair
from app.graph.nodes.n12_sql_execute import n12_sql_execute
from app.graph.state import GraphState


def build_recall_graph():
    """构建召回流水线（节点 1-8，自测用）

    Returns:
        编译后的 LangGraph 可执行对象
    """
    graph = StateGraph(GraphState)

    graph.add_node("n01_keyword_extraction", n01_keyword_extraction)
    graph.add_node("n02_field_recall", n02_field_recall)
    graph.add_node("n03_value_recall", n03_value_recall)
    graph.add_node("n04_metric_recall", n04_metric_recall)
    graph.add_node("n05_recall_merge", n05_recall_merge)
    graph.add_node("n06_table_filter", n06_table_filter)
    graph.add_node("n07_metric_filter", n07_metric_filter)
    graph.add_node("n08_context_supplement", n08_context_supplement)

    # n01 → 三路召回并行
    graph.add_edge(START, "n01_keyword_extraction")
    graph.add_edge("n01_keyword_extraction", "n02_field_recall")
    graph.add_edge("n01_keyword_extraction", "n03_value_recall")
    graph.add_edge("n01_keyword_extraction", "n04_metric_recall")

    # 三路并行 → 合并 → 过滤 → 上下文
    graph.add_edge("n02_field_recall", "n05_recall_merge")
    graph.add_edge("n03_value_recall", "n05_recall_merge")
    graph.add_edge("n04_metric_recall", "n05_recall_merge")
    graph.add_edge("n05_recall_merge", "n06_table_filter")
    graph.add_edge("n06_table_filter", "n07_metric_filter")
    graph.add_edge("n07_metric_filter", "n08_context_supplement")
    graph.add_edge("n08_context_supplement", END)

    return graph.compile()


# ----------------------------------------------------------------------
# 条件边路由函数
# ----------------------------------------------------------------------
def route_after_validate(state: dict) -> str:
    """节点 10 校验后的路由：通过 → 执行；失败且可纠错 → 纠错；否则终止

    Args:
        state: 全局状态

    Returns:
        下一节点名或 END
    """
    if state["validate_result"]["passed"]:
        return "n12_sql_execute"
    # SQL 为空（LLM 认为问题超出范围）或纠错轮数达到上限 → 终止
    if not state.get("sql") or state["repair_count"] >= get_settings().graph.max_repair_rounds:
        return END
    return "n11_sql_repair"


def route_after_execute(state: dict) -> str:
    """节点 12 执行后的路由：成功 → 终止；失败且可纠错 → 纠错；否则终止

    Args:
        state: 全局状态

    Returns:
        下一节点名或 END
    """
    if state.get("error") is None:
        return END
    if state["repair_count"] >= get_settings().graph.max_repair_rounds:
        return END
    return "n11_sql_repair"


def build_full_graph():
    """构建完整流水线（节点 1-12，含 SQL 校验纠错闭环）

    Returns:
        编译后的 LangGraph 可执行对象
    """
    graph = StateGraph(GraphState)

    graph.add_node("n01_keyword_extraction", n01_keyword_extraction)
    graph.add_node("n02_field_recall", n02_field_recall)
    graph.add_node("n03_value_recall", n03_value_recall)
    graph.add_node("n04_metric_recall", n04_metric_recall)
    graph.add_node("n05_recall_merge", n05_recall_merge)
    graph.add_node("n06_table_filter", n06_table_filter)
    graph.add_node("n07_metric_filter", n07_metric_filter)
    graph.add_node("n08_context_supplement", n08_context_supplement)
    graph.add_node("n09_sql_generation", n09_sql_generation)
    graph.add_node("n10_sql_validate", n10_sql_validate)
    graph.add_node("n11_sql_repair", n11_sql_repair)
    graph.add_node("n12_sql_execute", n12_sql_execute)

    # 召回链路
    graph.add_edge(START, "n01_keyword_extraction")
    graph.add_edge("n01_keyword_extraction", "n02_field_recall")
    graph.add_edge("n01_keyword_extraction", "n03_value_recall")
    graph.add_edge("n01_keyword_extraction", "n04_metric_recall")
    graph.add_edge("n02_field_recall", "n05_recall_merge")
    graph.add_edge("n03_value_recall", "n05_recall_merge")
    graph.add_edge("n04_metric_recall", "n05_recall_merge")
    graph.add_edge("n05_recall_merge", "n06_table_filter")
    graph.add_edge("n06_table_filter", "n07_metric_filter")
    graph.add_edge("n07_metric_filter", "n08_context_supplement")
    graph.add_edge("n08_context_supplement", "n09_sql_generation")
    graph.add_edge("n09_sql_generation", "n10_sql_validate")

    # 校验后条件边
    graph.add_conditional_edges("n10_sql_validate", route_after_validate,
                                {"n12_sql_execute": "n12_sql_execute", "n11_sql_repair": "n11_sql_repair", END: END})
    # 纠错回到校验（闭环）
    graph.add_edge("n11_sql_repair", "n10_sql_validate")
    # 执行后条件边（失败走纠错回环）
    graph.add_conditional_edges("n12_sql_execute", route_after_execute,
                                {"n11_sql_repair": "n11_sql_repair", END: END})

    return graph.compile()
