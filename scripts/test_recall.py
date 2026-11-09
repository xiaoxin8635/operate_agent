# -*- coding: utf-8 -*-
"""
召回链路自测脚本（M4）

职责：用验收场景问题跑通节点 1-8 召回图，打印每路召回结果与最终 schema_context，
验证：关键词抽取、三路并行召回、合并过滤、上下文拼装是否按预期工作。

前置条件：
    - docker 中间件已启动且 M2/M3 的数据与索引构建完成
    - .env 已配置 DeepSeek API Key（节点 1 需要 LLM）

运行方式（项目根目录）：
    python scripts/test_recall.py
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.clients import ClientManager
from app.core.logger import logger, setup_logger
from app.graph.build import build_recall_graph

# 验收场景（对应需求文档 2.3 节）
TEST_QUESTIONS = [
    "上个月完美日记的GMV是多少",
    "双十一当天各渠道的订单量和客单价",
    "上海地区女性用户的退货订单占比",
    "最近7天美妆类目的日销售额趋势",
    "帮我查一下昨天的销售额",
]


def run_one(graph, question: str) -> None:
    """跑单个问题的召回链路并打印关键结果

    Args:
        graph: 编译后的召回图
        question: 测试问题
    """
    print("\n" + "=" * 72)
    print(f"【问题】{question}")
    print("=" * 72)

    state = graph.invoke({"question": question, "node_trace": []})

    # 节点轨迹
    print(f"节点轨迹: {[t['node'] for t in state['node_trace']]}")

    # 关键词与时间
    kw = state["keywords"]
    dc = state["date_context"]
    print(f"关键词: entities={kw['entities']} metric_words={kw['metric_words']} dims={kw['dims']}")
    print(f"时间上下文: {dc['expr']} [{dc['start']} ~ {dc['end']}]")

    # 三路召回
    print(f"字段向量召回: {len(state['field_recall_results'])} 个")
    for f in state["field_recall_results"][:5]:
        print(f"    {f['table_name']}.{f['field_name']} ({f.get('alias')}) score={f['score']}")
    print(f"取值全文召回: {len(state['value_recall_results'])} 个")
    for v in state["value_recall_results"][:5]:
        print(f"    {v['table_name']}.{v['field_name']} = {v['value']} score={v['score']}")
    print(f"指标向量召回: {len(state['metric_recall_results'])} 个")
    for m in state["metric_recall_results"]:
        print(f"    {m['metric_name']} (alias={m.get('alias')}) score={m['score']}")

    # 合并结果
    print(f"候选字段(合并): {len(state['candidate_fields'])} 个 | 候选表: {[t['table_name'] for t in state['candidate_tables']]}")
    print(f"候选指标(过滤): {[m['metric_name'] for m in state['candidate_metrics']]}")

    # schema_context 摘要
    ctx = state["schema_context"]
    print(f"schema_context 长度: {len(ctx)} 字符")
    print("---- schema_context 预览(前 600 字) ----")
    print(ctx[:600])


def main() -> None:
    """自测主入口"""
    setup_logger(level="WARNING")   # 测试输出以 print 为主，日志降级减少干扰
    logger.info("========== M4 召回链路自测开始 ==========")

    ClientManager.init()   # 初始化 MySQL/Qdrant/ES/BGE 客户端
    graph = build_recall_graph()

    failed = 0
    for question in TEST_QUESTIONS:
        try:
            run_one(graph, question)
        except Exception as exc:  # noqa: BLE001 - 单个问题失败不影响其余场景
            failed += 1
            print(f"\n【失败】{question}\n错误: {exc}")

    ClientManager.close()
    print("\n" + "=" * 72)
    status = "全部通过" if failed == 0 else f"{failed} 个场景失败"
    print(f"自测结束: {status}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
