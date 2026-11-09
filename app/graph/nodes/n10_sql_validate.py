# -*- coding: utf-8 -*-
"""
节点 10：SQL 校验

校验规则（需求 FR-502，全部通过才放行）：
    1. 非空检查
    2. 语法解析（sqlglot MySQL 方言）
    3. 只读检查（AST 根节点必须是 SELECT/WITH；拒绝多语句）
    4. 表存在性（AST 提取表名 ⊆ 候选表集）
    5. 字段存在性（AST 提取列名 ⊆ 候选表字段全集）
    6. LIMIT 兜底（缺失时自动追加，防止全表扫描）

校验失败写入 error，由条件边路由进纠错节点或终止。
"""
import sqlglot
from sqlglot import exp

from app.core.config import get_settings
from app.core.logger import logger

# 允许的根节点类型（SELECT 及 CTE 包装）
ALLOWED_ROOT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)


def _extract_table_names(ast) -> set[str]:
    """提取 AST 中全部表名（含子查询/JOIN）

    Args:
        ast: sqlglot AST 根节点

    Returns:
        表名集合（小写）
    """
    return {t.name.lower() for t in ast.find_all(exp.Table)}


def _extract_column_names(ast) -> set[str]:
    """提取 AST 中全部列名（排除聚合函数参数与 * 通配）

    Args:
        ast: sqlglot AST 根节点

    Returns:
        列名集合（小写）
    """
    columns: set[str] = set()
    for col in ast.find_all(exp.Column):
        name = col.name
        if name and name != "*":
            columns.add(name.lower())
    return columns


def validate_sql(sql: str, allowed_tables: set[str], allowed_columns: set[str]) -> dict:
    """执行全部校验规则

    Args:
        sql: 待校验 SQL
        allowed_tables: 允许的表名集合（小写）
        allowed_columns: 允许的列名集合（小写）

    Returns:
        {passed: bool, errors: [str], ast: 解析后的 AST 或 None, sql: 校验后 SQL（可能追加了 LIMIT）}
    """
    errors: list[str] = []

    # 1. 非空
    if not sql or not sql.strip():
        return {"passed": False, "errors": ["SQL 为空"], "ast": None, "sql": sql}

    # 2. 语法解析（单语句，多语句由 read 参数拦截）
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except sqlglot.errors.ParseError as exc:
        return {"passed": False, "errors": [f"SQL 语法解析失败: {exc}"], "ast": None, "sql": sql}

    # 3. 多语句拒绝（防注释混淆注入多条语句）
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return {"passed": False, "errors": [f"仅允许单条语句，检测到 {len(statements)} 条"], "ast": None, "sql": sql}

    ast = statements[0]

    # 4. 只读检查：根节点必须是 SELECT 家族（WITH 会包装 Select，find 祖先判断）
    if isinstance(ast, exp.Subquery) or isinstance(ast, exp.With):
        inner = ast.find(ALLOWED_ROOT_TYPES)
        if inner is None:
            errors.append("仅允许 SELECT 查询")
    elif not isinstance(ast, ALLOWED_ROOT_TYPES):
        errors.append(f"仅允许 SELECT 查询，检测到: {type(ast).__name__}")

    # 5. 表存在性
    used_tables = _extract_table_names(ast)
    unknown_tables = used_tables - allowed_tables
    if unknown_tables:
        errors.append(f"使用了不存在的表: {sorted(unknown_tables)}，候选表: {sorted(allowed_tables)}")

    # 6. 字段存在性
    used_columns = _extract_column_names(ast)
    unknown_columns = used_columns - allowed_columns
    if unknown_columns:
        errors.append(f"使用了不存在的字段: {sorted(unknown_columns)}")

    # 6.1 禁止裸 SELECT *（投影层出现 Star 即拒绝；COUNT(*) 等函数参数不受影响）
    for select_node in ast.find_all(exp.Select):
        if any(isinstance(e, exp.Star) for e in select_node.expressions):
            errors.append("禁止 SELECT *，请显式列出查询字段")

    # 7. LIMIT 兜底：无 LIMIT 的 SELECT 自动追加（text 级追加，已是单语句安全）
    final_sql = sql.rstrip().rstrip(";")
    settings = get_settings()
    if not ast.find(exp.Limit):
        final_sql = f"{final_sql} LIMIT {settings.graph.sql_max_limit}"

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "ast": ast,
        "sql": final_sql,
    }


def n10_sql_validate(state: dict) -> dict:
    """节点 10 入口：校验 SQL 合法性

    Args:
        state: 全局状态（需含 sql / candidate_tables / candidate_fields）

    Returns:
        状态增量 {validate_result, error, sql(追加 LIMIT 后), node_trace}
    """
    sql = state.get("sql", "")
    logger.info("节点10 SQL校验开始")

    allowed_tables = {t["table_name"].lower() for t in state.get("candidate_tables", [])}
    allowed_columns = {f["field_name"].lower() for f in state.get("candidate_fields", [])}

    result = validate_sql(sql, allowed_tables, allowed_columns)

    if result["passed"]:
        logger.info("节点10 通过")
        return {
            "validate_result": {"passed": True, "errors": []},
            "sql": result["sql"],
            "error": None,
            "node_trace": [{"node": "n10_sql_validate", "status": "passed"}],
        }

    errors = result["errors"]
    logger.warning("节点10 未通过: {}", errors)
    return {
        "validate_result": {"passed": False, "errors": errors},
        "error": "SQL 校验失败: " + "; ".join(errors),
        "node_trace": [{"node": "n10_sql_validate", "status": "failed"}],
    }
