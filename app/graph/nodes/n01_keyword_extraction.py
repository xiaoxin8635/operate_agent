# -*- coding: utf-8 -*-
"""
节点 1：关键词抽取

职责：
    1. 规则解析时间表达（正则可靠，无需 LLM）：昨天/上月/最近N天/具体日期等
    2. LLM 抽取实体词（品牌/城市/渠道等）、指标词、维度词；失败时回退空集
       （实体缺失时由节点 3 用问题原文做 ES match 兜底）
"""
import json
import re
from datetime import date, timedelta

from app.core.logger import logger
from app.graph.llm import invoke_llm

# LLM 抽取 Prompt
KEYWORD_PROMPT_TEMPLATE = """你是电商数据分析专家。从用户问题中抽取关键信息。

用户问题：{question}

请严格按以下 JSON 格式输出（不要输出任何其他内容）：
{{"entities": ["品牌名/城市名/商品名/渠道名/类目名等实体词"], "metric_words": ["指标相关词，如销售额、订单量、退款率"], "dims": ["分组维度词，如按渠道、按天、按品牌"]}}

注意：
- 实体词必须是问题中出现的具体名称（如"完美日记"是品牌实体）
- 没有某类信息时输出空数组
"""

# 时间表达规则（正则 → 解析函数），按优先级依次匹配
DATE_PATTERNS: list[tuple[str, str]] = [
    (r"前天", "前天"),
    (r"昨天", "昨天"),
    (r"今天|当日", "今天"),
    (r"(?:最近|近)(\d+)天", "最近N天"),
    (r"双十一|双11", "双十一"),
    (r"六一八|618", "618"),
    (r"上个月|上月", "上个月"),
    (r"(?:这个月|本月|当月)", "本月"),
    (r"上周|上一周", "上周"),
    (r"(?:这个星期|本周|这一周)", "本周"),
    (r"今年", "今年"),
    (r"去年", "去年"),
]


def parse_date_context(question: str, today: date) -> dict:
    """规则解析问题中的时间表达为具体日期区间

    Args:
        question: 用户问题
        today: 今天日期（推算基准）

    Returns:
        {"expr": 命中的时间表达, "start": 开始日期, "end": 结束日期}；
        未命中时间表达时返回 {"expr": "", "start": None, "end": None}（由 SQL 生成节点决定是否加时间条件）
    """
    for pattern, kind in DATE_PATTERNS:
        match = re.search(pattern, question)
        if not match:
            continue

        expr = match.group(0)
        if kind == "前天":
            d = today - timedelta(days=2)
            return {"expr": expr, "start": d, "end": d}
        if kind == "昨天":
            d = today - timedelta(days=1)
            return {"expr": expr, "start": d, "end": d}
        if kind == "今天":
            return {"expr": expr, "start": today, "end": today}
        if kind == "最近N天":
            n = int(match.group(1))
            return {"expr": expr, "start": today - timedelta(days=n - 1), "end": today}
        if kind == "双十一":
            d = date(today.year, 11, 11)   # 双十一 → 当年 11 月 11 日
            return {"expr": expr, "start": d, "end": d}
        if kind == "618":
            d = date(today.year, 6, 18)    # 618 → 当年 6 月 18 日
            return {"expr": expr, "start": d, "end": d}
        if kind == "上个月":
            first_of_this_month = today.replace(day=1)
            end = first_of_this_month - timedelta(days=1)               # 上月最后一天
            start = end.replace(day=1)                                   # 上月第一天
            return {"expr": expr, "start": start, "end": end}
        if kind == "本月":
            start = today.replace(day=1)
            return {"expr": expr, "start": start, "end": today}
        if kind == "上周":
            this_monday = today - timedelta(days=today.weekday())
            last_monday = this_monday - timedelta(days=7)
            return {"expr": expr, "start": last_monday, "end": last_monday + timedelta(days=6)}
        if kind == "本周":
            monday = today - timedelta(days=today.weekday())
            return {"expr": expr, "start": monday, "end": today}
        if kind == "今年":
            return {"expr": expr, "start": today.replace(month=1, day=1), "end": today}
        if kind == "去年":
            return {"expr": expr, "start": today.replace(month=1, day=1, year=today.year - 1),
                    "end": today.replace(month=12, day=31, year=today.year - 1)}

    return {"expr": "", "start": None, "end": None}


def _llm_extract(question: str) -> dict:
    """LLM 抽取实体/指标词/维度词，JSON 解析失败时返回空结构

    Args:
        question: 用户问题

    Returns:
        {"entities": [...], "metric_words": [...], "dims": [...]}
    """
    prompt = KEYWORD_PROMPT_TEMPLATE.format(question=question)
    try:
        content = invoke_llm(prompt, purpose="keyword_extraction", temperature=0.0)
        # 容错：剥掉可能的 markdown 代码块包裹
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
        parsed = json.loads(content)
        return {
            "entities": [str(e) for e in parsed.get("entities", [])],
            "metric_words": [str(m) for m in parsed.get("metric_words", [])],
            "dims": [str(d) for d in parsed.get("dims", [])],
        }
    except Exception as exc:  # noqa: BLE001 - LLM 失败回退空集，由后续节点兜底
        logger.warning("关键词 LLM 抽取失败，回退空集: {}", exc)
        return {"entities": [], "metric_words": [], "dims": []}


def n01_keyword_extraction(state: dict) -> dict:
    """节点 1 入口：抽取关键词与时间上下文

    Args:
        state: 全局状态

    Returns:
        状态增量 {keywords, date_context, node_trace}
    """
    question = state["question"]
    logger.info("节点1 关键词抽取开始: {}", question)

    keywords = _llm_extract(question)
    date_context = parse_date_context(question, date.today())

    logger.info(
        "节点1 完成: entities={} metric_words={} time={}[{}~{}]",
        keywords["entities"], keywords["metric_words"],
        date_context["expr"], date_context["start"], date_context["end"],
    )
    return {
        "keywords": keywords,
        "date_context": {
            "expr": date_context["expr"],
            "start": str(date_context["start"]) if date_context["start"] else None,
            "end": str(date_context["end"]) if date_context["end"] else None,
        },
        "node_trace": [{"node": "n01_keyword_extraction", "status": "done"}],
    }
