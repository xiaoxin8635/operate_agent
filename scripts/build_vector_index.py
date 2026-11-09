# -*- coding: utf-8 -*-
"""
向量索引构建脚本：Meta MySQL → BGE Embedding → Qdrant

实际构建逻辑在 app/services/index_builder.py（与 API 重建入口共用），
本脚本为命令行薄壳。

运行方式（项目根目录）：
    python scripts/build_vector_index.py
    （首次运行会自动下载 BGE 模型约 100MB；下载慢可设置环境变量
      HF_ENDPOINT=https://hf-mirror.com 走国内镜像）
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，保证脚本可独立运行并导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.clients import ClientManager
from app.core.logger import setup_logger
from app.services.index_builder import build_vector_index


def main() -> None:
    """脚本主入口：初始化客户端 → 构建向量索引 → 统计输出"""
    setup_logger(level="INFO")
    print("========== 开始构建向量索引 ==========")
    ClientManager.init()
    try:
        result = build_vector_index()
        print(f"========== 向量索引构建完成: {result} ==========")
    finally:
        ClientManager.close()


if __name__ == "__main__":
    main()
