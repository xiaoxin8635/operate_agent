# -*- coding: utf-8 -*-
"""
节点 8：上下文补充

职责：拼装 SQL 生成所需的完整上下文（schema_context）：
    1. 候选表的字段清单：从 Meta MySQL 读取全字段（别名/类型/描述/样例），
       并将值召回证据（matched_values）合并进字段样例，减少 WHERE 条件漏写
    2. 命中指标口径（公式、关联字段）
    3. 日期上下文（今天日期 + 问题时间表达解析区间）
    4. 数据库方言（MySQL 8）
"""
from sqlalchemy import select

from app.core.clients import ClientManager
from app.core.logger import logger
from app.models.meta import MetaField, MetaTable


def _load_table_schema(table_names: list[str]) -> dict[str, dict]:
    """加载候选表及全字段的元数据

    Args:
        table_names: 候选表名列表

    Returns:
        {table_name: {"alias", "table_desc", "fields": [{field_name, field_alias, field_type, field_desc, examples, searchable}]}}
    """
    if not table_names:
        return {}
    result: dict[str, dict] = {}
    with ClientManager.get_engine().connect() as conn:
        # 表信息
        table_rows = conn.execute(
            select(MetaTable.table_name, MetaTable.alias, MetaTable.table_desc)
            .where(MetaTable.table_name.in_(table_names))
        ).mappings().all()
        for r in table_rows:
            result[r["table_name"]] = {"alias": r["alias"], "table_desc": r["table_desc"], "fields": []}

        # 字段信息（单次 JOIN 直接携带表名，避免逐字段查询）
        field_rows = conn.execute(
            select(MetaTable.table_name, MetaField)
            .join(MetaField, MetaField.table_id == MetaTable.id)
            .where(MetaTable.table_name.in_(table_names))
            .order_by(MetaField.id)
        ).all()
        for table_name, f in field_rows:
            if table_name in result:
                result[table_name]["fields"].append({
                    "field_name": f.field_name,
                    "field_alias": f.field_alias,
                    "field_type": f.field_type,
                    "field_desc": f.field_desc,
                    "examples": f.examples or [],
                    "searchable": bool(f.searchable),
                })
    return result


def _format_schema_section(table_name: str, table_meta: dict, matched_values: dict[str, list[str]]) -> str:
    """格式化单张表的 schema 描述

    Args:
        table_name: 表名
        table_meta: 表元数据
        matched_values: {field_name: [取值证据]}

    Returns:
        文本块（DDL 风格 + 中文描述 + 样例）
    """
    lines = [f"表 {table_name}（{table_meta['alias']}）：{table_meta['table_desc']}"]
    for field in table_meta["fields"]:
        # 样例与值召回证据合并（证据置前，最多展示 8 个）
        evidence = matched_values.get(field["field_name"], [])
        examples = (evidence + [e for e in field["examples"] if e not in evidence])[:8]
        example_str = f"，样例取值: {examples}" if examples else ""
        lines.append(f"  - {field['field_name']} {field['field_type']} -- {field['field_alias']}：{field['field_desc']}{example_str}")
    return "\n".join(lines)


def n08_context_supplement(state: dict) -> dict:
    """节点 8 入口：拼装 schema_context

    Args:
        state: 全局状态（需含 candidate_tables / candidate_fields / candidate_metrics / date_context）

    Returns:
        状态增量 {schema_context, node_trace}
    """
    candidate_tables = state.get("candidate_tables", [])
    candidate_metrics = state.get("candidate_metrics", [])
    date_context = state.get("date_context", {})
    logger.info("节点8 上下文补充开始: {} 张候选表", len(candidate_tables))

    table_names = [t["table_name"] for t in candidate_tables]
    schema_map = _load_table_schema(table_names)

    # 值召回证据按字段归集（仅候选表内的）
    matched_values: dict[str, list[str]] = {}
    for f in state.get("candidate_fields", []):
        if f["table_name"] in table_names and f.get("matched_values"):
            matched_values.setdefault(f["table_name"], {}).setdefault(f["field_name"], [])
            matched_values[f["table_name"]][f["field_name"]].extend(f["matched_values"])

    # 表 schema 段
    schema_sections = [
        _format_schema_section(t["table_name"], schema_map[t["table_name"]],
                               matched_values.get(t["table_name"], {}))
        for t in candidate_tables if t["table_name"] in schema_map
    ]

    # 指标口径段
    metric_lines = [
        f"- {m['metric_name']}（别名: {', '.join(m.get('alias') or [])}）：{m.get('formula')}，主表 {m['table_name']}"
        for m in candidate_metrics
    ]

    # 日期上下文段（注入今天日期，LLM 可据此推算"上月"等表达）
    from datetime import date as _date
    today = _date.today()
    date_lines = [f"今天是 {today.isoformat()}。"]
    if date_context.get("expr"):
        date_lines.append(
            f"问题中的时间表达「{date_context['expr']}」对应日期区间: "
            f"[{date_context.get('start')}, {date_context.get('end')}]，SQL 时间条件必须使用该区间。"
        )

    schema_context = "\n\n".join([
        "【候选表结构】\n" + "\n\n".join(schema_sections),
        "【指标口径】\n" + ("\n".join(metric_lines) if metric_lines else "（无命中指标）"),
        "【日期上下文】\n" + "\n".join(date_lines),
        "【数据库】MySQL 8.0，数库名见各表前缀说明。",
    ])

    logger.info("节点8 完成: schema_context {} 字符", len(schema_context))
    return {
        "schema_context": schema_context,
        "node_trace": [{"node": "n08_context_supplement", "status": "done"}],
    }
