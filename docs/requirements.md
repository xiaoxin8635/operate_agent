# 经营分析 Agent（自然语言问数系统）需求文档

> 版本：v1.0
> 日期：2026-11-09
> 状态：需求评审中
> 性质：复刻「胖胖龙-经营分析 agent」项目

---

## 1. 项目概述

### 1.1 项目背景

公司电商业务中，运营、商品和管理人员查询经营数据时面临三大痛点：

| 痛点 | 描述 | 后果 |
|------|------|------|
| 查数门槛高 | 不会写 SQL，查数需找数据同学排队提需求 | 响应慢，数据同学被打断 |
| 数据口径不统一 | 「GMV」「订单量」等指标各人理解与算法不同 | 数据对不上，沟通成本高 |
| 跨表查询复杂 | 多表 JOIN、字段多、取值杂，人工关联易出错 | 查询结果不可信 |

### 1.2 项目目标

构建一套**自然语言问数系统**：用户用自然语言提问（如「上个月完美日记的 GMV 是多少」），系统自动完成：

```
理解问题 → 召回相关表/字段/指标/取值 → 生成 SQL → 校验 → 纠错 → 执行 → 返回结果
```

### 1.3 目标用户

- 电商运营人员（日常看数、拉数据）
- 商品管理人员（商品维度的分析）
- 管理人员（经营指标概览）

### 1.4 项目性质

本阶段为**复刻项目**：数据仓库使用模拟电商数据，验证 NL2SQL + RAG 全链路可行性，形成可二次开发的工程骨架。复刻完成后可替换为真实数据仓库与真实元数据。

---

## 2. 需求分析

### 2.1 核心能力拆解

围绕三大痛点，系统需要三层核心能力：

```
┌───────────────────────────────────────────────────────────┐
│  能力层三：稳定性闭环                                       │
│  SQL 合法性校验（只读/语法/表字段存在性）                    │
│  失败自动纠错（带错误信息重新生成，最多 N 轮）               │
│  SSE 进度流式输出 + Loguru 请求级日志追踪                   │
├───────────────────────────────────────────────────────────┤
│  能力层二：检索增强（RAG）                                  │
│  向量召回：问题语义 → 匹配字段/指标的名称、描述、别名         │
│  全文召回：问题中的取值（品牌名/城市名）→ 定位字段            │
│  业务过滤：数仓分层、表规模、指标关联关系剪枝候选集           │
├───────────────────────────────────────────────────────────┤
│  能力层一：元数据知识库（统一口径的根基）                     │
│  YAML 声明式管理：表/字段/别名/描述/样例/指标口径             │
│  构建脚本同步至 Meta MySQL，作为全系统唯一口径来源            │
│  向量索引（Qdrant）+ 取值全文索引（ES）从元数据派生          │
└───────────────────────────────────────────────────────────┘
```

### 2.2 为什么需要 RAG 而不是把 Schema 全部塞给 LLM

- 数仓表数量多、字段更多，全量 Schema 超出上下文窗口且噪声大；
- 将候选集裁剪到「与问题最相关的几张表、十几个字段」，SQL 生成质量显著提升；
- 字段取值（examples）注入 Prompt，可大幅减少 WHERE 条件漏写与取值编造。

### 2.3 典型用户场景（验收基准用例）

| # | 用户问题 | 期望行为 |
|---|----------|----------|
| S1 | 上个月完美日记的 GMV 是多少 | 命中 GMV 指标；值召回命中 brand=完美日记；自动推导上月日期区间；生成单表聚合 SQL |
| S2 | 双十一当天各渠道的订单量和客单价 | 命中订单量/客单价指标；GROUP BY channel；日期精确到天 |
| S3 | 上海地区女性用户的退货订单占比 | 跨 users / orders 表 JOIN；值召回 city=上海；条件 gender=女 |
| S4 | 哪个品牌的退款率最高 | 指标召回 + 排序 + LIMIT；自动选择退款金额字段 |
| S5 | 最近7天美妆类目的日销售额趋势 | 日期区间 + 按天 GROUP BY + 类目条件 |
| S6 | 帮我查一下昨天的销售额（口语化） | 别名匹配：销售额→GMV（支付口径），不歧义 |
| S7 | 删掉所有订单表 | SQL 校验拦截非 SELECT 语句，拒绝执行并提示只读 |

---

## 3. 总体架构

### 3.1 技术栈

| 层次 | 技术 | 用途 |
|------|------|------|
| 语言 | Python 3.10+ | 主语言 |
| 编排 | LangGraph | 12 节点状态图流水线 |
| LLM 框架 | LangChain | LLM 调用、Prompt 模板 |
| LLM | DeepSeek API（OpenAI 兼容） | 关键词抽取、SQL 生成、SQL 纠错 |
| 服务 | FastAPI + SSE (sse-starlette) | 问数接口，流式返回节点进度 |
| 元数据库 | MySQL 8 + SQLAlchemy | Meta 元数据 + 数仓业务数据 |
| 向量库 | Qdrant | 字段/指标语义索引 |
| 全文检索 | Elasticsearch 8 | 字段取值索引 |
| Embedding | BAAI/bge-small-zh-v1.5（本地，CPU 可跑） | 文本向量化 |
| 配置 | YAML（表元数据声明）+ pydantic-settings（应用配置） | 声明式管理 |
| 日志 | Loguru + 请求 ID | 并发场景日志追踪 |
| 基础设施 | Docker Compose | MySQL / ES / Qdrant 一键部署 |

### 3.2 系统架构图

```
                        ┌─────────────────────────┐
                        │   用户（运营/商品/管理）  │
                        └───────────┬─────────────┘
                                    │ 自然语言问题
                                    ▼
                      ┌──────────────────────────┐
                      │   FastAPI 服务层          │
                      │  POST /api/query (SSE)   │──► 节点进度流式推送
                      └───────────┬──────────────┘
                                  ▼
┌────────────────────────── LangGraph 12 节点流水线 ──────────────────────────┐
│                                                                            │
│  ①关键词抽取 ──► ②字段召回 ──► ③字段值召回 ──► ④指标召回                    │
│                                                      │                     │
│                     ⑤召回合并 ◄───────────────────────┘                    │
│                          │                                                 │
│                          ▼                                                 │
│                    ⑥表过滤 ──► ⑦指标过滤 ──► ⑧上下文补充                    │
│                                                │                           │
│                                                ▼                           │
│                                          ⑨SQL 生成                          │
│                                                │                           │
│                                                ▼                           │
│                                          ⑩SQL 校验 ──不通过──► ⑪SQL 纠错   │
│                                                │通过              │        │
│                                                ▼                  └─►回⑨   │
│                                          ⑫SQL 执行 ──执行报错──► ⑪SQL 纠错  │
│                                                │成功                        │
│                                                ▼                           │
│                                          返回结果 + SQL + 节点轨迹           │
└────────────────────────────────────────────────────────────────────────────┘
        │                    │                     │              │
        ▼                    ▼                     ▼              ▼
   Meta MySQL           Qdrant                Elasticsearch    DW MySQL
  （元数据口径）     （字段/指标向量索引）     （字段取值全文索引）  （模拟业务数据）
```

### 3.3 核心数据流（一次问数的完整生命周期）

1. 用户提问 → FastAPI 生成 `request_id`，贯穿全链路日志；
2. **关键词抽取**：LLM 从问题中抽取时间、实体、指标类关键词；
3. **三路召回**（并行概念上）：字段向量召回 / 字段值 ES 召回 / 指标向量召回；
4. **合并 → 过滤**：候选集去重合并，按数仓分层与关联关系过滤表和指标；
5. **上下文补充**：拼装候选表 DDL 风格描述、字段描述与样例取值、指标口径、日期上下文（今天日期等）、数据库方言信息；
6. **SQL 生成**：LLM 按 Prompt 约束输出单条 SELECT；
7. **校验**：只读检查（禁 DML/DDL）、语法解析、表字段存在性比对元数据；
8. **纠错**：校验失败或执行报错时，携带错误信息进入纠错节点重新生成（上限 3 轮）；
9. **执行**：SQLAlchemy 只读连接执行，返回行列数据；
10. SSE 流式推送每一步进度，最终返回 `{answer, sql, rows, trace}`。

---

## 4. 功能需求详述

### 4.1 模块一：元数据管理（FR-100）

#### FR-101 YAML 元数据声明

每张数仓表一份 YAML，声明以下内容：

```yaml
table:
  name: dw_orders                      # 物理表名
  alias: 订单表                         # 中文别名
  desc: 电商订单事实表，记录下单与支付信息
  layer: dw                            # 数仓分层 ods/dw/dm
  owner: data-team
fields:
  - name: pay_amount
    alias: 支付金额
    desc: 用户实际支付金额（扣除优惠后），单位元
    type: DECIMAL(12,2)
    examples: [129.90, 59.00]          # 样例值
    searchable: false                  # 是否参与取值全文索引
  - name: brand
    alias: 品牌
    desc: 订单商品品牌
    type: VARCHAR(64)
    examples: [完美日记, 花西子]        # 高频取值，写入 ES
    searchable: true
```

指标单独 YAML 声明：

```yaml
metrics:
  - name: gmv
    alias: [GMV, 商品交易总额, 销售额]
    desc: 商品交易总额，支付口径
    formula: SUM(pay_amount)
    table: dw_orders
    related_fields: [pay_amount, pay_date]
```

**验收**：YAML 语法校验工具可检测缺失字段、类型错误；示例覆盖所有表。

#### FR-102 元数据同步脚本

- 输入：`config/metadata/*.yaml`；
- 输出：写入 Meta MySQL（建表/更新），记录同步日志；
- 幂等性：重复执行不产生脏数据（按 table_name/field_name upsert）；
- 同步前做 schema 校验，失败即中断并报出具体 YAML 文件与行号。

### 4.2 模块二：索引构建（FR-200）

#### FR-201 向量索引（Qdrant）

| 集合名 | 内容 | payload |
|--------|------|---------|
| `field_index` | 字段向量：`字段名 + 别名 + 描述` 拼接后 Embedding | table_name, field_name, alias, desc |
| `metric_index` | 指标向量：`指标名 + 别名 + 描述 + 公式` | metric_name, alias, formula, table |

- Embedding 模型：`BAAI/bge-small-zh-v1.5`（512 维），本地加载，CPU 推理；
- 重建策略：脚本全量重建（删除集合重建），元数据变更后手动触发；
- 向量化文本模板需固定，保证召回一致性。

#### FR-202 取值全文索引（Elasticsearch）

| 索引名 | 文档结构 |
|--------|----------|
| `field_value_index` | `{table_name, field_name, value, keyword_analyzer}` |

- 数据来源：元数据 YAML 中 `searchable: true` 字段的高频取值（从 DW MySQL 实际聚合 TOP N，如品牌、城市、类目名、渠道名）；
- 分词：中文使用 `ik_max_word`（若镜像无 ik 插件，则回退 standard + ngram）；
- 查询方式：match 查询，返回命中的字段定位信息。

#### FR-203 构建脚本

- `scripts/build_vector_index.py`：读 Meta MySQL → Embedding → 写 Qdrant；
- `scripts/build_es_index.py`：连 DW MySQL 聚合取值 → 写 ES；
- 两个脚本均支持 `--rebuild` 全量重建，输出构建统计（条数、耗时）。

### 4.3 模块三：检索召回（FR-300）

#### FR-301 关键词抽取

- 输入：用户问题；
- 输出：结构化关键词 `{time_keywords, entity_keywords, metric_keywords, dims}`；
- 实现：LLM 抽取（Prompt 约束 JSON 输出）+ 规则兜底（正则匹配日期表达：「昨天/上月/最近7天」等）。

#### FR-302 字段向量召回

- 输入：用户问题原文（可选叠加关键词）；
- Qdrant top-k（默认 k=20，可配置），score 阈值过滤（默认 0.6）；
- 输出：候选字段列表 `{table_name, field_name, score}`。

#### FR-303 字段值召回（ES）

- 输入：问题中的实体词（品牌名、城市名等）；
- ES match 查询，返回 `{table_name, field_name, matched_value}`；
- 该结果直接注入后续字段候选集，并作为 examples 证据。

#### FR-304 指标向量召回

- Qdrant `metric_index` top-k（默认 k=5）；
- 命中指标后通过元数据反查其 `table` 与 `related_fields`，直接纳入候选表字段。

#### FR-305 召回合并与业务过滤

- 合并：三路候选字段去重（table+field 粒度）；
- 表过滤规则：候选字段所在表 + 指标关联表进入候选表集；数仓分层优先级（dm > dw > ods）；同主题分层表去重（如订单表保留一层）；
- 指标过滤：指标关键词/向量得分高于阈值的指标保留，其余剔除。

### 4.4 模块四：LangGraph 编排（FR-400）

#### FR-401 状态定义

全局 State（TypedDict）包含：`question`、`keywords`、`candidate_fields`、`candidate_values`、`candidate_metrics`、`candidate_tables`、`schema_context`、`sql`、`validate_result`、`execute_result`、`repair_count`、`error`、`node_trace`。

#### FR-402 十二节点定义

| # | 节点 | 输入 | 处理 | 输出 |
|---|------|------|------|------|
| 1 | keyword_extraction | question | LLM 抽取 + 规则兜底 | keywords |
| 2 | field_recall | question, keywords | Qdrant 向量召回 | candidate_fields(部分) |
| 3 | value_recall | entity_keywords | ES 全文召回 | candidate_values |
| 4 | metric_recall | question, keywords | Qdrant 指标召回 | candidate_metrics |
| 5 | recall_merge | 2/3/4 输出 | 去重合并、值召回字段并入候选 | candidate_fields(全量) |
| 6 | table_filter | candidate_fields, candidate_metrics | 元数据反查、分层过滤 | candidate_tables |
| 7 | metric_filter | candidate_metrics, keywords | 阈值+相关性过滤 | candidate_metrics(过滤后) |
| 8 | context_supplement | 上述全部 | 拼 DDL 描述/样例/口径/日期/方言 | schema_context |
| 9 | sql_generation | question, schema_context | LLM 生成 SELECT | sql |
| 10 | sql_validate | sql | 只读检查+语法+表字段比对 | validate_result(pass/fail) |
| 11 | sql_repair | sql, error, schema_context | LLM 携错误重生成 | sql(修正) → 回 10 |
| 12 | sql_execute | sql | SQLAlchemy 只读执行 | rows, columns |

**条件边**：
- 节点 10 `fail` 且 `repair_count < 3` → 节点 11 → 回节点 10；
- 节点 10 `fail` 且 `repair_count >= 3` → 直接结束，返回失败说明（含最后一次错误）；
- 节点 12 执行报错 → 节点 11（执行错误也走纠错，如超时改写、字段歧义修正）。

**节点 2/3/4 并行**：LangGraph 支持同层多节点并行执行后汇入节点 5。

#### FR-403 节点可观测

- 每个节点执行前/后向 SSE 推送进度事件：`{node, status, cost_ms, brief}`；
- `node_trace` 记录全链路节点轨迹，随最终结果返回，保证可解释性。

### 4.5 模块五：SQL 生成与校验纠错（FR-500）

#### FR-501 SQL 生成 Prompt 要素

Prompt 注入内容（顺序固定）：
1. 角色设定与硬约束（只生成 SELECT、禁 `*` 尽量明确列、必须带时间条件（若问题含时间）、LIMIT 上限 1000）；
2. 用户问题；
3. 候选表：表描述 + 字段列表（字段名、类型、别名、描述、样例取值）；
4. 命中指标口径（公式、关联字段、关联表）；
5. 日期上下文（今天是 YYYY-MM-DD，便于推算「上月」）；
6. 数据库方言（MySQL 8）与输出格式（仅 SQL，代码块包裹）。

#### FR-502 SQL 校验规则（全部通过才放行）

| 规则 | 实现 |
|------|------|
| 只读 | 解析 AST，仅允许 SELECT/WITH，拒绝 INSERT/UPDATE/DELETE/DROP/ALTER 等 |
| 语法 | sqlglot 解析 MySQL 方言，解析失败即拒绝 |
| 表存在性 | AST 提取表名 ⊆ 候选表集 |
| 字段存在性 | AST 提取列名 ⊆ 候选表字段全集 |
| 安全兜底 | 拒绝多语句（分号分隔多条）、拒绝注释混淆注入 |

#### FR-503 SQL 纠错

- 纠错 Prompt 输入：原 SQL + 错误信息（校验错误或数据库报错）+ 完整 schema_context；
- 输出修正后的 SQL，再次走校验流程；
- `repair_count` 上限 3，超限终止并返回可读失败原因。

#### FR-504 SQL 执行

- 独立只读连接（连接参数只读事务）；
- 超时控制（默认 10s）；
- 返回 `{columns, rows(截断至200行), row_total}`，聚合类查询正常返回单行。

### 4.6 模块六：API 服务（FR-600）

#### FR-601 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/query` | 问数主接口，SSE 流式返回：`progress` 事件（节点进度）→ `result` 事件（最终答案）→ `[DONE]` |
| POST | `/api/index/rebuild` | 触发向量/取值索引重建（管理用，后续可加鉴权） |
| GET | `/api/health` | 健康检查（含 MySQL/ES/Qdrant 连通性） |

#### FR-602 `/api/query` 请求与响应

```jsonc
// 请求
{ "question": "上个月完美日记的GMV是多少", "top_k": 20 }

// SSE 事件流示例
event: progress
data: {"node": "keyword_extraction", "status": "running", "brief": "抽取关键词"}

event: progress
data: {"node": "sql_execute", "status": "done", "cost_ms": 128}

event: result
data: {
  "answer": "上月（2026-10-01~2026-10-31）完美日记 GMV 为 1,234,567.89 元",
  "sql": "SELECT SUM(pay_amount) FROM dw_orders ...",
  "rows": [{"gmv": 1234567.89}],
  "trace": [{"node": "keyword_extraction", "cost_ms": 412, ...}]
}
```

- `answer` 由 LLM 基于执行结果生成自然语言回答（可选，配置开关）；
- 断连处理：客户端断开，服务端取消后续 LLM 调用与执行。

#### FR-603 客户端生命周期管理

- FastAPI lifespan 统一初始化/关闭：MySQL Engine（SQLAlchemy pool）、QdrantClient、ES Client、BGE 模型、httpx（LLM）；
- 全局单例获取，避免每请求重复建连与重复加载模型。

### 4.7 模块七：日志与可观测（FR-700）

- Loguru 全局接管 logging；
- 中间件生成 `request_id`（UUID 短码），通过 `logger.contextualize` 注入每条日志；
- 日志格式：`时间 | 级别 | request_id | 模块 | 消息`；
- LLM 调用记录：耗时、token 用量、Prompt 摘要（问题原文）、响应摘要（SQL）；
- 文件日志按天滚动，保留 14 天，控制台同步输出。

---

## 5. 数据设计

### 5.1 模拟电商数仓（DW MySQL）

| 表名 | 中文 | 关键字段 | 数据量 |
|------|------|----------|--------|
| `dw_orders` | 订单事实表 | order_id, user_id, product_id, channel, brand, order_status, order_amount, discount_amount, pay_amount, refund_amount, quantity, order_date, pay_date | 50 万（近 13 个月） |
| `dw_products` | 商品维表 | product_id, product_name, category_id, brand, price, stock, shelf_date | 2,000 |
| `dw_users` | 用户维表 | user_id, user_name, gender, age, city, user_level, register_date | 10 万 |
| `dw_categories` | 类目维表 | category_id, category_name, parent_category_id | 200（含美妆/服饰等） |
| `dw_traffic` | 流量事实表 | stat_date, channel, product_id, pv, uv, click_cnt | 30 万 |

- 生成脚本 `scripts/init_dw_data.py` 使用 Faker + 自定义规则，保证取值真实感（品牌：完美日记/花西子/华为/小米…；城市：北上广深杭等；渠道：淘宝/抖音/京东/拼多多）；
- 时间跨度：近 13 个月，含促销日（双11、618）销量突增，便于验证时间条件；
- 订单状态：已完成/已退款/待付款 等，退款金额字段支持退款率指标。

### 5.2 元数据库（Meta MySQL）

| 表 | 说明 |
|----|------|
| `meta_tables` | id, table_name(uk), alias, desc, layer, owner, updated_at |
| `meta_fields` | id, table_id, field_name, alias, desc, field_type, examples(JSON), searchable, uk(table_id+field_name) |
| `meta_metrics` | id, metric_name(uk), alias(JSON), desc, formula, table_name, related_fields(JSON) |
| `meta_sync_log` | id, batch_no, yaml_file, status, message, created_at |

### 5.3 Qdrant 集合

| 集合 | 向量维度 | 距离 | payload |
|------|----------|------|---------|
| `field_index` | 512（bge-small-zh-v1.5） | Cosine | table_name, field_name, alias, desc |
| `metric_index` | 512 | Cosine | metric_name, alias, formula, table_name |

### 5.4 Elasticsearch 索引

```
field_value_index:
  mappings:
    table_name: { type: keyword }
    field_name: { type: keyword }
    value:      { type: text, analyzer: ik_max_word, search_analyzer: ik_smart }
```

---

## 6. 非功能需求

| 编号 | 需求 | 指标 |
|------|------|------|
| NFR-1 | 端到端响应时间 | P95 ≤ 30s（含 2 次以上 LLM 调用）；检索阶段 ≤ 3s |
| NFR-2 | 并发 | 支持 10 并发问数请求，互不串扰（request_id 隔离） |
| NFR-3 | SQL 安全 | 强制只读；注入类输入（S7 场景）100% 拦截 |
| NFR-4 | 可解释性 | 每次问数返回完整节点轨迹与最终 SQL |
| NFR-5 | 可配置 | top-k、阈值、纠错轮数、LLM 参数、模型路径全部配置化（`config/app_settings.yaml` + `.env`） |
| NFR-6 | 可移植 | `docker compose up -d` 一键起中间件；应用本身可 `uvicorn` 直跑 |

---

## 7. 实施里程碑

| 阶段 | 内容 | 验收物 |
|------|------|--------|
| M1 基础设施 | docker-compose（MySQL/ES/Qdrant）+ 项目骨架 + 配置体系 | 中间件连通，health 接口通过 |
| M2 数据与元数据 | 模拟数据生成 + YAML 元数据 + 同步脚本 + Meta MySQL | Meta 表数据完整，脚本幂等 |
| M3 索引构建 | BGE 加载 + Qdrant/ES 构建脚本 | 两索引可查询，条数与元数据一致 |
| M4 召回链路 | 节点 1-8（关键词→召回→合并→过滤→上下文） | 给定问题输出合理候选集（单元验证） |
| M5 SQL 闭环 | 节点 9-12（生成→校验→纠错→执行） | S1-S7 场景全部符合预期 |
| M6 服务化 | FastAPI + SSE + 生命周期 + Loguru 日志 | SSE 全链路进度推送正常，日志含 request_id |
| M7 联调验收 | 端到端回归 + 性能观测 + 文档 | NFR 指标达标，README 完善 |

---

## 8. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| ES 镜像无 ik 中文分词插件 | 取值召回精度下降 | 方案 A：使用自带 ik 的第三方镜像；方案 B：standard + ngram 兜底 |
| 本地 BGE 首次下载慢 | M3 阻塞 | 提前下载模型到本地缓存目录（HF_HOME 指定国内镜像 hf-mirror.com） |
| DeepSeek 生成 SQL 幻觉字段 | 查询失败 | 校验节点拦截 + 纠错闭环 + examples 注入降低概率 |
| 模拟数据分布失真导致召回验证失真 | 验收通过但真实场景失效 | 取值尽量贴近真实电商业务；后续换真实库只需重跑 M2-M3 |
| SSE 代理/网关缓冲导致前端看不到流式进度 | 体验差 | 文档注明 Nginx 需 `proxy_buffering off`；本地直连开发 |

---

## 9. 验收标准

1. 第 2.3 节 S1-S7 场景全部通过；
2. SSE 可观察到 ≥ 12 个节点的进度事件，最终 result 事件含 `answer/sql/rows/trace`；
3. 任一节点失败时，请求不 500，SSE 推送错误事件并给可读原因；
4. `docker compose up -d` 后按 README 顺序执行 4 个脚本 + 启动应用，即可完整复现；
5. 并发 10 个不同问题，日志中 request_id 互不串扰，结果一一对应。

---

## 10. 范围外（本期不做）

- 多轮对话与上下文追问（问数接口为单轮）；
- 权限体系与租户隔离（管理接口暂不加鉴权）；
- 查询结果图表化渲染（返回结构化数据，前端可视化另行规划）；
- 真实数仓接入与增量元数据同步（复刻验证通过后立项）。
