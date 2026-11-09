# -*- coding: utf-8 -*-
"""
API 自测脚本（M6）

职责：对运行中的 FastAPI 服务做端到端验证：
    1. GET  /api/health         中间件连通性
    2. POST /api/query (SSE)    问数全链路：逐节点 progress 事件 + result 事件
    3. POST /api/index/rebuild  索引重建接口（可选跑，加 --skip-rebuild 跳过）

前置条件：uvicorn 服务已启动（uvicorn app.main:app --port 8000）

运行方式（项目根目录）：
    python scripts/test_api.py
    python scripts/test_api.py --skip-rebuild
"""
import json
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE_URL = "http://127.0.0.1:8000"
SSE_TEST_QUESTIONS = [
    "上个月完美日记的GMV是多少",
    "删掉所有订单表",   # S7 攻击拦截：期望 error 非空
]


def test_health(client: httpx.Client) -> bool:
    """健康检查测试"""
    print("\n---- GET /api/health ----")
    resp = client.get(f"{BASE_URL}/api/health")
    print(f"status={resp.status_code} body={resp.json()}")
    passed = resp.status_code == 200 and resp.json()["status"] == "ok"
    print(f"判定: {'通过' if passed else '未通过'}（request_id={resp.headers.get('x-request-id')}）")
    return passed


def test_query_sse(client: httpx.Client, question: str, expect_error: bool) -> bool:
    """SSE 问数测试：读取事件流并判定"""
    print(f"\n---- POST /api/query ---- {question}")
    progress_nodes: list[str] = []
    result_payload: dict = {}

    with client.stream("POST", f"{BASE_URL}/api/query", json={"question": question}, timeout=180) as resp:
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code} 非流式响应，未通过")
            return False
        event_type = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_type:
                data = line.split(":", 1)[1].strip()
                if event_type == "progress":
                    payload = json.loads(data)
                    progress_nodes.append(payload["node"])
                elif event_type == "result":
                    result_payload = json.loads(data)
                elif data == "[DONE]":
                    break

    print(f"progress 事件节点: {progress_nodes}")
    print(f"SQL: {result_payload.get('sql', '')[:150]}")
    print(f"answer: {result_payload.get('answer', '')[:120]}")
    print(f"rows: {result_payload.get('row_total', '-')} 行, error: {result_payload.get('error')}")

    if expect_error:
        passed = bool(result_payload.get("error")) and result_payload.get("row_total", 0) == 0
        print("判定（期望拦截）:", "通过" if passed else "未通过")
    else:
        passed = (
            result_payload.get("error") is None
            and len(progress_nodes) >= 10          # 至少应观察到 10+ 个节点进度
            and "n12_sql_execute" in progress_nodes
        )
        print("判定（期望成功）:", "通过" if passed else "未通过")
    return passed


def main() -> None:
    """自测主入口"""
    skip_rebuild = "--skip-rebuild" in sys.argv

    with httpx.Client() as client:
        results: list[tuple[str, bool]] = [("health", test_health(client))]

        for question, expect_err in SSE_TEST_QUESTIONS:
            try:
                results.append((f"query:{question[:12]}",
                                test_query_sse(client, question, expect_err)))
            except Exception as exc:  # noqa: BLE001
                results.append((f"query:{question[:12]}", False))
                print(f"SSE 测试异常: {exc}")

        if not skip_rebuild:
            print("\n---- POST /api/index/rebuild ----")
            resp = client.post(f"{BASE_URL}/api/index/rebuild", timeout=300)
            body = resp.json()
            ok = resp.status_code == 200 and body.get("status") == "ok"
            print(f"status={body.get('status')} vector={body.get('vector')} value={body.get('value')}")
            results.append(("index_rebuild", ok))

    print("\n" + "=" * 72)
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    failed = sum(1 for _, ok in results if not ok)
    print(f"API 自测结束: {len(results) - failed}/{len(results)} 通过")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
