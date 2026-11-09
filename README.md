# 经营分析 Agent（自然语言问数系统）

自然语言提问 → 召回数仓表/字段/指标/取值 → LangGraph 12 节点流水线生成/校验/纠错 SQL → 只读执行 → SSE 流式返回节点进度与结果。

技术栈：Python 3.10+ / FastAPI / LangGraph / LangChain / DeepSeek API / MySQL 8 / Qdrant / Elasticsearch 8 / BGE(bge-small-zh-v1.5) / Loguru / Docker Compose

## 目录结构

```
operate_agent/
├── CLAUDE.md                # AI 开发规则（人也可读，了解项目约定）
├── docs/
│   └── requirements.md      # 需求文档（唯一需求来源）
├── docker-compose.yml       # MySQL + ES + Qdrant 基础设施
├── docker/init_sql/         # MySQL 首次启动自动建库脚本
├── config/
│   ├── app_settings.yaml    # 应用业务参数（召回 top-k/纠错轮数/LLM 参数等）
│   └── metadata/            # 表/字段/指标元数据 YAML（5 表 + 8 指标）
├── scripts/
│   ├── init_dw_data.py      # 模拟电商数造数（5 表，订单约 50 万）
│   ├── sync_meta.py         # YAML → Meta MySQL（幂等 + diff 同步）
│   ├── build_vector_index.py# BGE → Qdrant 向量索引构建
│   ├── build_es_index.py    # 高频取值 → ES 全文索引构建
│   ├── test_recall.py       # M4 召回链路自测（节点 1-8）
│   ├── test_sql_loop.py     # M5 SQL 闭环自测（S1-S7 场景）
│   └── test_api.py          # M6 API + SSE 自测
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── core/                # 配置 / 日志 / 中间件 / 客户端生命周期
│   ├── api/                 # 路由（health / query SSE / index rebuild）
│   ├── graph/               # LangGraph：state / build / llm / nodes(1-12)
│   ├── services/            # Embedding / Qdrant / ES / 索引构建 / 回答生成
│   └── models/              # Meta 元数据库 ORM
└── logs/                    # 运行日志（按天滚动，git 忽略）
```

## 快速开始

### 1. 启动基础设施（MySQL / ES / Qdrant）

```bash
cd d:/ai_play/operate_agent
cp .env.example .env         # 然后编辑 .env 填入 DeepSeek API Key
docker compose up -d
docker compose ps            # 等待三个容器 healthy
```

MySQL 映射宿主机 **3307** 端口，首次启动自动创建 `dw_ecom`（数仓）与 `meta_db`（元数据）。

### 2. 安装依赖（建议虚拟环境）

```bash
python -m venv venv
source venv/Scripts/activate      # Git Bash；Windows CMD 用 venv\Scripts\activate.bat
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3. 配置 .env

- `MYSQL_ROOT_PASSWORD` / `MYSQL__PASSWORD`：两处保持一致
- `LLM__API_KEY`：DeepSeek API Key（https://platform.deepseek.com）

### 4. 一键初始化数据与索引（按顺序执行）

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 可选：BGE 模型国内镜像加速

python scripts/init_dw_data.py        # 造数（约 2-4 分钟）
python scripts/sync_meta.py           # 元数据同步（表 5 / 字段 51 / 指标 8）
python scripts/build_vector_index.py  # Qdrant 向量索引（首次含模型下载约 100MB）
python scripts/build_es_index.py      # ES 取值索引（ik 缺失自动 ngram 回退）
```

### 5. 启动服务

```bash
# 先检查端口占用，被占用先 taskkill //f //pid <pid>
netstat -ano | findstr :8000
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. 运行自测（三个脚本按序执行）

```bash
python scripts/test_recall.py     # 召回链路：5 个场景打印三路召回与 schema_context
python scripts/test_sql_loop.py   # SQL 闭环：S1-S6 应执行成功，S7 应被拦截
python scripts/test_api.py        # API：health + SSE 问数 + 索引重建
```

### 7. 手动体验

```bash
# SSE 事件流（progress 节点进度 → result 最终结果 → [DONE]）
curl -N -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question": "上个月完美日记的GMV是多少"}'
```

Swagger 文档：http://127.0.0.1:8000/docs

## 12 节点流水线

```
①关键词抽取 ─► ②字段召回 ─┐
              ③取值召回 ─┼─► ⑤合并 ► ⑥表过滤 ► ⑦指标过滤 ► ⑧上下文补充
              ④指标召回 ─┘                                      │
                                                                ▼
                                                          ⑨SQL 生成
                                                                │
                                                          ⑩SQL 校验 ──失败──► ⑪纠错（≤3轮）─┐
                                                                │通过                     │
                                                                ▼◄───────────────────────┘
                                                          ⑫只读执行 ──报错──► ⑪纠错
                                                                │成功
                                                                ▼
                                                    SSE result（answer/sql/rows/trace）
```

安全闭环：sqlglot AST 校验（只读/单语句/表字段存在性/禁 SELECT *）+ MySQL `SET TRANSACTION READ ONLY` 数据库层兜底。

## 模块进度

| 模块 | 内容 | 状态 |
|------|------|------|
| M0 | 需求文档 | 已完成 |
| M1 | 基础设施 + 项目骨架 + 配置体系 | 已完成 |
| M2 | 模拟数据 + YAML 元数据 + 同步脚本 | 已完成 |
| M3 | BGE + Qdrant/ES 索引构建 | 已完成 |
| M4 | LangGraph 节点 1-8（召回链路） | 已完成 |
| M5 | SQL 生成/校验/纠错/执行（节点 9-12） | 已完成 |
| M6 | FastAPI + SSE + 日志追踪 | 已完成 |

## 开发规则

见 [CLAUDE.md](CLAUDE.md)：禁止虚假代码、配置分层、SQL 安全边界、蟑螂法则排查等。
