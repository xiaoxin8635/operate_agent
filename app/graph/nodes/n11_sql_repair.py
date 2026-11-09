# -*- coding: utf-8 -*-
"""
节点 11：SQL 纠错

职责：校验失败或执行报错时，携带错误信息 + 完整 schema_context 让 LLM 重新生成 SQL。
纠错轮数由 repair_count 控制（条件边检查上限），本节点只负责 +1 并重新生成。
"""
from app.core.config import get_settings
from app.core.logger import logger
from app.graph.llm import invoke_llm
from app.graph.nodes.n09_sql_generation import extract_sql

REPAIR_PROMPT_TEMPLATE = """你是资深的电商数据仓库 SQL 专家。上一轮生成的 SQL 存在问题，请修正后重新生成。

【原 SQL】
```sql
{sql}
```

【错误信息】
{error}

【硬性约束】
1. 只能生成 SELECT 语句，禁止任何写操作；
2. 禁止 SELECT *，必须显式列出查询字段；
3. 若问题含时间条件，必须使用【日期上下文】中给出的具体日期区间；
4. 查询末尾必须带 LIMIT，最大 {max_limit}；
5. 聚合字段必须使用 AS 中文别名；
6. 只使用【候选表结构】中真实存在的表和字段；
7. 只输出修正后的 SQL，用 ```sql 代码块包裹，不要输出任何解释。

{schema_context}

【用户问题】
{question}

请生成修正后的 SQL："""


def n11_sql_repair(state: dict) -> dict:
    """节点 11 入口：携错误信息重新生成 SQL

    Args:
        state: 全局状态（需含 sql / error / schema_context / question / repair_count）

    Returns:
        状态增量 {sql, repair_count(+1), error(清空待重校验), node_trace}
    """
    settings = get_settings()
    sql = state.get("sql", "")
    error = state.get("error", "未知错误")
    repair_count = state.get("repair_count", 0) + 1
    logger.info("节点11 SQL纠错开始: 第 {} 轮", repair_count)

    prompt = REPAIR_PROMPT_TEMPLATE.format(
        sql=sql, error=error, schema_context=state.get("schema_context", ""),
        question=state["question"], max_limit=settings.graph.sql_max_limit,
    )
    content = invoke_llm(prompt, purpose=f"sql_repair_round{repair_count}", temperature=0.0)
    repaired = extract_sql(content)

    return {
        "sql": repaired,
        "repair_count": repair_count,
        "error": None,   # 清空错误，交由节点 10 重新校验
        "node_trace": [{"node": "n11_sql_repair", "status": "done", "round": repair_count}],
    }
