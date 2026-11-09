# -*- coding: utf-8 -*-
"""
节点 9：SQL 生成

职责：
    1. Prompt 注入（顺序固定）：角色与硬约束 → schema_context → 用户问题 → 输出格式
    2. LLM 生成单条 SELECT
    3. 响应解析：剥离 markdown 代码块，提取纯 SQL；解析失败置空（校验节点拦截）
"""
import re

from app.core.config import get_settings
from app.core.logger import logger
from app.graph.llm import invoke_llm

# SQL 生成 Prompt（硬约束前置，保证 LLM 遵守只读与 LIMIT 规则）
SQL_PROMPT_TEMPLATE = """你是资深的电商数据仓库 SQL 专家。根据给定的表结构、指标口径与用户问题，生成一条 MySQL 查询 SQL。

【硬性约束】
1. 只能生成 SELECT 语句，禁止任何 INSERT/UPDATE/DELETE/DROP 等写操作；
2. 必须显式列出查询字段，禁止 SELECT *；
3. 若问题含时间条件，必须使用【日期上下文】中给出的具体日期区间，禁止自行推算；
4. 查询末尾必须带 LIMIT，最大 {max_limit}；
5. 聚合字段必须使用 AS 中文别名（如 SUM(pay_amount) AS gmv）；
6. 表间关联使用 WHERE 或 JOIN 均可，注意关联字段的一致性（如 user_id、product_id）；
7. 只输出 SQL，用 ```sql 代码块包裹，不要输出任何解释。

{schema_context}

【用户问题】
{question}

请生成 SQL："""


def extract_sql(content: str) -> str:
    """从 LLM 响应中提取纯 SQL（剥离 markdown 代码块）

    Args:
        content: LLM 响应原文

    Returns:
        SQL 文本（提取失败返回空串，由校验节点拦截）
    """
    content = content.strip()
    match = re.search(r"```sql\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 无代码块时：若响应整体像 SQL（以 SELECT/WITH 开头）则直接使用
    if re.match(r"^(SELECT|WITH)\b", content, re.IGNORECASE):
        return content.rstrip(";").strip()
    return ""


def n09_sql_generation(state: dict) -> dict:
    """节点 9 入口：生成初始 SQL

    Args:
        state: 全局状态（需含 question 与 schema_context）

    Returns:
        状态增量 {sql, repair_count, error, node_trace}
    """
    settings = get_settings()
    question = state["question"]
    schema_context = state.get("schema_context", "")
    logger.info("节点9 SQL生成开始")

    prompt = SQL_PROMPT_TEMPLATE.format(schema_context=schema_context, question=question,
                                        max_limit=settings.graph.sql_max_limit)
    content = invoke_llm(prompt, purpose="sql_generation", temperature=0.0)
    sql = extract_sql(content)

    if not sql:
        logger.warning("节点9: 未解析到 SQL（问题可能超出问数范围）")
        return {
            "sql": "",
            "repair_count": state.get("repair_count", 0),
            "error": "未能生成 SQL（问题可能不是数据查询，或超出数据范围）",
            "node_trace": [{"node": "n09_sql_generation", "status": "done", "sql": False}],
        }

    logger.info("节点9 完成: SQL {} 字符", len(sql))
    return {
        "sql": sql,
        "repair_count": state.get("repair_count", 0),
        "error": None,
        "node_trace": [{"node": "n09_sql_generation", "status": "done", "sql": True}],
    }
