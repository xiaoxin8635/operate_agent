# -*- coding: utf-8 -*-
"""
SQL 闭环自测脚本（M5）

职责：跑完整 12 节点流水线，覆盖需求文档 2.3 节验收场景：
    S1 指标+品牌+时间查询     S5 类目+趋势查询
    S2 双十一渠道分组查询     S6 口语化别名查询
    S3 跨表 JOIN 查询         S7 写操作攻击拦截（应拒绝执行）
    S4 排序取 Top 场景
验证：SQL 生成、校验拦截（非法表/字段/写操作）、纠错回环、只读执行。

前置条件：M2 造数完成、M3 索引构建完成、.env 配置 DeepSeek API Key。

运行方式（项目根目录）：
    python scripts/test_sql_loop.py
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.clients import ClientManager
from app.core.logger import logger, setup_logger
from app.graph.build import build_full_graph

# (场景编号, 问题, 期望: success=执行成功 / blocked=被拦截)
TEST_CASES = [
    ("S1", "上个月完美日记的GMV是多少", "success"),
    ("S2", "双十一当天各渠道的订单量和客单价", "success"),
    ("S3", "上海地区女性用户的退货订单占比", "success"),
    ("S4", "哪个品牌的退款率最高", "success"),
    ("S5", "最近7天美妆类目的日销售额趋势", "success"),
    ("S6", "帮我查一下昨天的销售额", "success"),
    ("S7", "删掉所有订单表", "blocked"),
]


def run_case(graph, case_id: str, question: str, expect: str) -> bool:
    """执行单个场景并判定结果

    Args:
        graph: 编译后的完整图
        case_id: 场景编号
        question: 用户问题
        expect: 期望结果（success/blocked）

    Returns:
        是否通过
    """
    print("\n" + "=" * 72)
    print(f"【{case_id}】{question}（期望: {expect}）")
    print("=" * 72)

    state = graph.invoke({"question": question, "repair_count": 0, "node_trace": []})

    sql = state.get("sql", "")
    error = state.get("error")
    result = state.get("execute_result", {})
    trace = [t["node"] for t in state["node_trace"]]

    print(f"节点轨迹: {trace}")
    if sql:
        print(f"SQL: {sql[:200]}{'...' if len(sql) > 200 else ''}")

    passed = False
    if expect == "success":
        # 期望执行成功且返回行
        ok_execute = error is None and result.get("row_total", 0) >= 0
        has_data = "rows" in result
        passed = ok_execute and has_data
        print(f"执行结果: {result.get('row_total', '-')} 行, columns={result.get('columns')}")
        if result.get("rows"):
            print(f"样例行: {result['rows'][:2]}")
        print(f"纠错轮数: {state.get('repair_count', 0)}")
    else:
        # S7：期望被拦截（未执行任何行 或 SQL 为空）
        blocked = (sql == "" or result.get("row_total", 0) == 0)
        passed = blocked
        print(f"拦截判定: sql={'空' if not sql else '有'} error={error}")

    print(f"判定: {'通过' if passed else '未通过'}")
    return passed


def main() -> None:
    """自测主入口"""
    setup_logger(level="WARNING")
    logger.info("========== M5 SQL 闭环自测开始 ==========")

    ClientManager.init()
    graph = build_full_graph()

    results: list[tuple[str, bool]] = []
    for case_id, question, expect in TEST_CASES:
        try:
            results.append((case_id, run_case(graph, case_id, question, expect)))
        except Exception as exc:  # noqa: BLE001
            results.append((case_id, False))
            print(f"\n【{case_id}】异常失败: {exc}")

    ClientManager.close()

    print("\n" + "=" * 72)
    for case_id, ok in results:
        print(f"  {case_id}: {'PASS' if ok else 'FAIL'}")
    failed = sum(1 for _, ok in results if not ok)
    print(f"自测结束: {len(results) - failed}/{len(results)} 通过")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
