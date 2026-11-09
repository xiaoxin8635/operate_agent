# -*- coding: utf-8 -*-
"""
Elasticsearch 全文检索服务

职责：
    1. 索引管理：探测 ik 中文分词可用性，不可用时自动回退 ngram 方案（需求 FR-202 风险应对）
    2. 全量重建：删除索引重建 mapping 并批量写入取值文档（构建脚本使用）
    3. 取值检索：实体词 → 定位字段（LangGraph 字段值召回节点使用）

索引 mapping（field_value_index）：
    table_name: keyword     表名（精确过滤）
    field_name: keyword     字段名（精确过滤）
    value:      text        取值（分词检索）
"""
from typing import Any

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.core.config import get_settings
from app.core.logger import logger

# ik 分词探测文本（含中文词组，若插件缺失该分析器会返回 400）
IK_PROBE_TEXT = "美妆护肤口红"


def _probe_ik(es: Elasticsearch) -> bool:
    """探测 ik_max_word 分词器是否可用

    Args:
        es: ES 客户端

    Returns:
        可用返回 True；不可用（400/异常）返回 False
    """
    try:
        es.indices.analyze(analyzer="ik_max_word", text=IK_PROBE_TEXT)
        return True
    except Exception:  # noqa: BLE001 - 插件缺失时抛 400/NotFound，统一视为不可用
        return False


def _build_mappings(use_ik: bool) -> dict[str, Any]:
    """按分词方案构造索引 mapping

    Args:
        use_ik: 是否使用 ik 分词

    Returns:
        ES mapping 定义
    """
    if use_ik:
        value_field = {"type": "text", "analyzer": "ik_max_word", "search_analyzer": "ik_smart"}
    else:
        # 回退方案：standard 分词 + 1~2 gram 索引，中文以双字词为主，可覆盖大部分匹配
        value_field = {
            "type": "text",
            "analyzer": "value_ngram_analyzer",
            "search_analyzer": "standard",
        }
    return {
        "settings": {
            # 开发环境小索引，分片 1 副本 0
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "value_ngram_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "value_ngram_filter"],
                    }
                },
                "filter": {
                    "value_ngram_filter": {"type": "ngram", "min_gram": 1, "max_gram": 2}
                },
            },
        },
        "mappings": {
            "properties": {
                "table_name": {"type": "keyword"},
                "field_name": {"type": "keyword"},
                "value": value_field,
            }
        },
    }


def rebuild_index(es: Elasticsearch, docs: list[dict[str, Any]]) -> int:
    """全量重建取值索引：删除 → 重建（自动探测 ik）→ 批量写入

    Args:
        es: ES 客户端
        docs: [{"table_name", "field_name", "value"}, ...]

    Returns:
        写入文档数
    """
    settings = get_settings()
    index_name = settings.es.value_index

    use_ik = _probe_ik(es)
    logger.info("ik 中文分词探测结果: {}，采用 {}", "可用" if use_ik else "不可用",
                "ik_max_word/ik_smart" if use_ik else "ngram(1-2) 回退方案")

    if es.indices.exists(index=index_name):
        es.indices.delete(index=index_name)
        logger.info("已删除旧索引: {}", index_name)

    es.indices.create(index=index_name, **_build_mappings(use_ik))

    # bulk 批量写入（每批自动流式生成）
    actions = (
        {"_index": index_name, "_source": {"table_name": d["table_name"], "field_name": d["field_name"], "value": d["value"]}}
        for d in docs
    )
    success, errors = bulk(es, actions, raise_on_error=False, request_timeout=30)
    if errors:
        logger.warning("部分文档写入失败: {} 条", len(errors))

    # 刷新使写入立即可检索
    es.indices.refresh(index=index_name)
    logger.info("ES 索引重建完成: {} ({} 文档, {} 失败)", index_name, success, len(errors) if errors else 0)
    return success


def search_values(es: Elasticsearch, text: str, size: int) -> list[dict[str, Any]]:
    """取值全文检索：实体词 → 命中的字段定位

    Args:
        es: ES 客户端
        text: 实体词（如"完美日记"）
        size: 返回条数上限

    Returns:
        [{"table_name", "field_name", "value", "score"}, ...] 按得分降序
    """
    settings = get_settings()
    resp = es.search(
        index=settings.es.value_index,
        query={"match": {"value": {"query": text}}},
        size=size,
    )
    results = []
    for hit in resp["hits"]["hits"]:
        source = hit["_source"]
        results.append({
            "table_name": source.get("table_name"),
            "field_name": source.get("field_name"),
            "value": source.get("value"),
            "score": round(hit["_score"], 4),
        })
    return results
