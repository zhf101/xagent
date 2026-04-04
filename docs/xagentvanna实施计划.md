# Xagent Vanna 独立模块实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Xagent 中独立实现一套 `xagent.vanna` 模块，支持面向用户已配置数据源的 schema 采集、训练知识沉淀、检索增强 SQL 生成、可选自动执行，以及 ask 成功后的候选样例回流。

**Architecture:** 本方案不复用 `datamake_sql_asset` 体系，而是新建一套 Vanna 专用模型。整体采用三层资产结构：`结构事实层` 负责保真存储数据源 schema、表、字段、默认值、注释、枚举和取值方式；`训练知识层` 负责存储 `question_sql/schema_summary/documentation` 等可检索知识；`检索切片层` 负责 embedding 和召回。检索层统一采用 `PostgreSQL + pgvector`，结构元数据与向量索引同库治理，运行阶段继续复用现有 `Text2SQLDatabase` 作为数据源宿主，复用现有 OpenAI-compatible chat model 创建逻辑，复用现有 `execute_sql_query` 与 SQL 审批链作为最终执行基础设施。

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, pgvector, Pydantic, existing Text2SQL datasource host, existing OpenAI-compatible model stack, existing SQL execution tool, pytest

---

## 一、实施边界

### 1. 本模块负责什么

- 建立独立的 Vanna 知识库宿主
- 从 `Text2SQLDatabase` 采集 schema 结构事实
- 保存表级 DDL、表注释、字段注释、默认值、取值方式、枚举值、外键关系
- 保存 SQL 样例、schema 摘要、业务文档
- 生成 embedding chunk 并做分桶召回
- 基于召回结果组装 Prompt 生成 SQL
- 可选自动执行 SQL
- ask 成功后沉淀候选 `question_sql`

### 2. 本模块不负责什么

- 不替代 `Text2SQLDatabase` 的数据源连接管理
- 不复用 `datamake_sql_asset` 模型和服务
- 不实现复杂前端页面
- 不实现多智能体 SQL 规划
- 不实现复杂 reranker 模型
- 不实现通用资产中心

### 3. 允许复用的现有能力

- `src/xagent/web/models/text2sql.py`
  - 数据源连接宿主
- 现有 OpenAI-compatible LLM 创建逻辑
- `src/xagent/core/tools/core/sql_tool.py`
  - `execute_sql_query`
- 现有 SQL 审批链

---

## 二、核心设计原则

### 1. 必须区分“结构事实”和“训练知识”

前一版方案的问题在于把 `ddl` 和 `schema_summary` 混成了同一层。现在明确拆开：

- 结构事实层
  - 存数据库真实结构，保真、可追踪、可刷新
- 训练知识层
  - 存给 Text2SQL 用的可读知识，不要求完全保真，但要求利于召回和 Prompt
- 检索切片层
  - 存 embedding 和 chunk，不直接承担治理

### 2. 从第一版就区分“候选条目”和“正式条目”

训练条目生命周期只允许：

- `candidate`
- `published`
- `archived`

其中：

- bootstrap 导入的 schema 摘要默认 `candidate`
- ask 成功自动沉淀的样例默认 `candidate`
- 人工录入的高质量样例默认可直接 `published`

### 3. `system_short` 和 `env` 必须从数据源宿主下沉到全链路

新增两个统一字段：

- `system_short`
  - 系统简称
- `env`
  - 环境标识，如 `dev/test/uat/prod`

规则：

- 源头定义在 `text2sql_databases`
- Vanna 全部核心表都冗余保存这两个字段
- 写入 Vanna 记录时，以数据源当前值做快照
- 后续即使数据源改名或切环境，历史记录仍保留当时上下文

这样做的目的：

- 方便按系统和环境做过滤
- 方便检索时做硬隔离
- 方便审计和问题排查
- 避免大量运行时 join `text2sql_databases`

### 4. 结构采集必须保留字段级细节

不能只存一份 `ddl_text`。必须同时保留：

- 表级 DDL
- 表注释
- 字段类型
- 字段注释
- 默认值原文
- 默认值类型
- 外键来源
- 取值方式
- 枚举值
- 采样值

### 5. 训练知识不直接等于结构事实

例如：

- `vanna_schema_columns` 保存字段事实
- `vanna_training_entries(entry_type=schema_summary)` 保存从这些字段事实归纳出来的“适合 LLM 阅读”的摘要

---

## 三、数据模型总览

本模块新增 7 张核心表：

1. `vanna_knowledge_bases`
2. `vanna_schema_harvest_jobs`
3. `vanna_schema_tables`
4. `vanna_schema_columns`
5. `vanna_training_entries`
6. `vanna_embedding_chunks`
7. `vanna_ask_runs`

关系如下：

- 一个 `knowledge_base` 绑定一个默认数据源
- 一个 `knowledge_base` 下有多次 `schema_harvest_job`
- 一个 `schema_harvest_job` 产生多条 `schema_table`
- 一条 `schema_table` 下有多条 `schema_column`
- 一个 `knowledge_base` 下有多条 `training_entry`
- 一条 `training_entry` 下有多条 `embedding_chunk`
- 一个 `knowledge_base` 下有多次 `ask_run`

---

## 四、表结构设计

### 4.1 `vanna_knowledge_bases`

用途：
- 一条记录代表一套 Vanna 知识库。
- 管理边界按“用户 + 数据源 + 知识库”划分。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_code` | String(255), unique, index | 稳定编码，如 `vanna.ds12.default` |
| `name` | String(255) | 知识库名称 |
| `description` | Text | 描述 |
| `owner_user_id` | Integer, index | 所属用户 |
| `owner_user_name` | String(255) | 所属用户名 |
| `datasource_id` | Integer, index | 绑定 `Text2SQLDatabase.id` |
| `datasource_name` | String(255) | 冗余数据源名 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `db_type` | String(64), index | 数据库类型 |
| `dialect` | String(64), index | SQL 方言 |
| `status` | String(32), index | `draft/active/archived` |
| `default_top_k_sql` | Integer | 默认 SQL 样例召回数 |
| `default_top_k_schema` | Integer | 默认 schema 召回数 |
| `default_top_k_doc` | Integer | 默认文档召回数 |
| `embedding_model` | String(128) | 默认 embedding 模型 |
| `llm_model` | String(128) | 默认生成模型 |
| `last_train_at` | DateTime | 最近训练时间 |
| `last_ask_at` | DateTime | 最近问答时间 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

约束建议：

- `kb_code` 唯一
- `(owner_user_id, datasource_id, status)` 可高频过滤

### 4.2 `vanna_schema_harvest_jobs`

用途：
- 记录一次 schema 采集请求与结果。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `status` | String(32), index | `running/completed/failed` |
| `harvest_scope` | String(32) | `all/schemas/tables` |
| `schema_names_json` | JSON | 指定 schema |
| `table_names_json` | JSON | 指定表 |
| `request_payload_json` | JSON | 原始请求 |
| `result_payload_json` | JSON | 结果摘要 |
| `error_message` | Text | 错误信息 |
| `create_user_id` | Integer, index | 发起人 |
| `create_user_name` | String(255) | 发起人中文姓名 |
| `started_at` | DateTime | 开始时间 |
| `completed_at` | DateTime | 完成时间 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

### 4.3 `vanna_schema_tables`

用途：
- 存一张表的结构事实。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `harvest_job_id` | Integer, index | 来源采集任务 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `catalog_name` | String(255) | catalog |
| `schema_name` | String(255), index | schema 名 |
| `table_name` | String(255), index | 表名 |
| `table_type` | String(64) | 表类型 |
| `table_comment` | Text | 表注释 |
| `table_ddl` | Text | 原始 DDL |
| `primary_key_json` | JSON | 主键结构 |
| `foreign_keys_json` | JSON | 外键结构 |
| `indexes_json` | JSON | 索引结构 |
| `constraints_json` | JSON | 约束结构 |
| `row_count_estimate` | Integer | 估算行数 |
| `content_hash` | String(64), index | 内容 hash |
| `status` | String(32), index | `active/stale/archived` |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

约束建议：

- `(kb_id, schema_name, table_name, content_hash)` 允许历史快照共存
- `(kb_id, schema_name, table_name, status=active)` 只有一条活跃记录

### 4.4 `vanna_schema_columns`

用途：
- 存字段级结构事实。
- 这是字段注释、默认值、取值方式等的正式宿主。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `table_id` | Integer, index | 所属表 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `schema_name` | String(255), index | schema 名 |
| `table_name` | String(255), index | 表名 |
| `column_name` | String(255), index | 字段名 |
| `ordinal_position` | Integer | 字段顺序 |
| `data_type` | String(128) | 逻辑数据类型 |
| `udt_name` | String(128) | 底层类型名 |
| `is_nullable` | Boolean | 是否可空 |
| `default_raw` | Text | 原始默认值文本 |
| `default_kind` | String(32), index | `literal/function/sequence/expression/none` |
| `column_comment` | Text | 字段注释 |
| `is_primary_key` | Boolean | 是否主键 |
| `is_foreign_key` | Boolean | 是否外键 |
| `foreign_table_name` | String(255) | 外键目标表 |
| `foreign_column_name` | String(255) | 外键目标字段 |
| `is_generated` | Boolean | 是否生成列 |
| `generation_expression` | Text | 生成表达式 |
| `value_source_kind` | String(32), index | `free_text/boolean/enum/dictionary_table/foreign_key/generated/code_rule/unknown` |
| `allowed_values_json` | JSON | 可选值列表 |
| `sample_values_json` | JSON | 采样值 |
| `stats_json` | JSON | 统计摘要 |
| `semantic_tags_json` | JSON | 语义标签 |
| `content_hash` | String(64), index | 内容 hash |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

说明：

- `default_raw` 用来保真保存默认值
- `default_kind` 用来让上层理解默认值来源
- `value_source_kind` 用来表达“字段取值方式”
- `allowed_values_json` 用来承载枚举、字典值、有限集合

### 4.5 `vanna_training_entries`

用途：
- 存可用于召回和 Prompt 的训练知识。
- 不是结构事实的替代，而是结构事实的派生和增强。

允许类型：

- `question_sql`
- `documentation`
- `schema_summary`

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `entry_code` | String(255), unique, index | 稳定编码 |
| `entry_type` | String(32), index | 条目类型 |
| `source_kind` | String(32), index | `manual/bootstrap_schema/bootstrap_history/auto_train/imported` |
| `source_ref` | String(255) | 来源引用，如 `table:12`、`task:123` |
| `lifecycle_status` | String(32), index | `candidate/published/archived` |
| `quality_status` | String(32), index | `unverified/verified/rejected` |
| `title` | String(255) | 标题 |
| `question_text` | Text | 问题文本，仅 `question_sql` |
| `sql_text` | Text | SQL 文本，仅 `question_sql` |
| `sql_explanation` | Text | SQL 说明 |
| `doc_text` | Text | 文档正文，`documentation/schema_summary` 使用 |
| `schema_name` | String(255), index | 关联 schema |
| `table_name` | String(255), index | 关联表 |
| `business_domain` | String(128), index | 业务域 |
| `system_name` | String(128), index | 系统名 |
| `subject_area` | String(128), index | 主题域 |
| `statement_kind` | String(32), index | SQL 类型 |
| `tables_read_json` | JSON | 读取表 |
| `columns_read_json` | JSON | 读取字段 |
| `output_fields_json` | JSON | 输出字段 |
| `variables_json` | JSON | 参数变量 |
| `tags_json` | JSON | 标签 |
| `verification_result_json` | JSON | 验证结果 |
| `quality_score` | Float | 质量分 |
| `content_hash` | String(64), index | 内容 hash |
| `create_user_id` | Integer, index | 创建人 |
| `create_user_name` | String(255) | 创建人中文姓名 |
| `verified_by` | String(255) | 审核人 |
| `verified_at` | DateTime | 审核时间 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

### 4.6 `vanna_embedding_chunks`

用途：
- 存用于 embedding 和召回的切片。
- 该表直接使用 PostgreSQL `vector` 列，由 `pgvector` 提供 ANN 检索能力。
- 不再把向量存在 JSON，也不额外引入独立向量数据库。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `entry_id` | Integer, index | 来源训练条目 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `source_table` | String(64), index | 来源表名 |
| `source_row_id` | Integer, index | 来源行 id |
| `chunk_type` | String(32), index | `question_sql_pair/schema_table_summary/documentation` |
| `chunk_order` | Integer | 顺序 |
| `chunk_text` | Text | 原始 chunk |
| `embedding_text` | Text | 用于 embedding 的文本 |
| `embedding_model` | String(128), index | embedding 模型 |
| `embedding_dim` | Integer | 向量维度 |
| `embedding_vector` | Vector(dim) | pgvector 原生向量，Phase 1 要求同一知识库固定维度 |
| `distance_metric` | String(16) | `cosine/l2/ip` |
| `token_count_estimate` | Integer | chunk 长度估计 |
| `lifecycle_status` | String(32), index | 与条目状态镜像，便于检索过滤 |
| `metadata_json` | JSON | 附加元数据 |
| `chunk_hash` | String(64), index | 去重 hash |
| `created_at` | DateTime | 创建时间 |

索引建议：

- BTree:
  - `(kb_id, chunk_type, lifecycle_status, embedding_model)`
  - `(entry_id, chunk_type)`
- pgvector:
  - `embedding_vector vector_cosine_ops`
- Phase 1 默认：
  - 小规模先可用精确检索
  - 数据量上来后切到 `HNSW`
  - 批量导入场景可评估 `IVFFlat`

约束建议：

- 一个 `knowledge_base` 只绑定一个 `embedding_model`
- 一个 `knowledge_base` 只允许一个固定 `embedding_dim`
- 若未来切换 embedding 模型，走“重建索引”而不是混存多维向量

### 4.7 `vanna_ask_runs`

用途：
- 记录一次 ask 的完整事实。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | 主键 |
| `kb_id` | Integer, index | 所属知识库 |
| `datasource_id` | Integer, index | 数据源 |
| `system_short` | String(64), index | 系统简称，来自数据源快照 |
| `env` | String(32), index | 环境，来自数据源快照 |
| `task_id` | Integer, nullable, index | 关联任务 |
| `question_text` | Text | 用户原始问题 |
| `rewritten_question` | Text | 重写后问题 |
| `retrieval_snapshot_json` | JSON | 召回命中快照 |
| `prompt_snapshot_json` | JSON | Prompt 快照 |
| `generated_sql` | Text | 生成 SQL |
| `sql_confidence` | Float | 生成置信度 |
| `execution_mode` | String(32), index | `preview/auto_run` |
| `execution_status` | String(32), index | `generated/executed/failed/waiting_approval` |
| `execution_result_json` | JSON | 执行结果 |
| `approval_status` | String(32), index | `not_required/pending/approved/rejected` |
| `auto_train_entry_id` | Integer, nullable, index | ask 成功后沉淀的候选样例 |
| `create_user_id` | Integer, index | 发起人 |
| `create_user_name` | String(255) | 发起人中文姓名 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

---

## 五、字段级信息的采集与存储策略

### 5.1 DDL 如何存

DDL 不再作为唯一事实源，只作为表级事实的一部分：

- `vanna_schema_tables.table_ddl`
  - 保存原始 DDL

同时配套保存：

- `table_comment`
- `primary_key_json`
- `foreign_keys_json`
- `indexes_json`
- `constraints_json`

### 5.2 字段注释如何存

字段注释保存到：

- `vanna_schema_columns.column_comment`

来源优先级：

1. 数据库注释元数据
2. information_schema 扩展字段
3. 无则为空

### 5.3 默认值如何存

默认值保存两份：

- `default_raw`
  - 原始默认值，如 `CURRENT_TIMESTAMP`、`0`、`'N'`
- `default_kind`
  - 标识默认值类型

`default_kind` 建议取值：

- `literal`
- `function`
- `sequence`
- `expression`
- `none`

### 5.4 字段取值方式如何存

字段取值方式使用：

- `value_source_kind`

建议取值：

- `free_text`
- `boolean`
- `enum`
- `dictionary_table`
- `foreign_key`
- `generated`
- `code_rule`
- `unknown`

### 5.5 枚举值和样例值如何存

- `allowed_values_json`
  - 明确有限值列表
- `sample_values_json`
  - 样本值列表
- `stats_json`
  - 字段统计信息

判定顺序建议：

1. 原生 enum 类型
2. check constraint 可解析为有限集合
3. foreign key 指向字典表
4. 规则推断
5. 数据采样

---

## 六、训练知识的生成策略

### 6.1 不直接把 `schema_columns` 用作 Prompt

原因：

- 字段事实太碎
- 直接拼 prompt 成本太高
- LLM 不适合直接吃原始元数据洪水

所以需要从结构事实层派生出 `schema_summary` 训练条目。

### 6.2 `schema_summary` 生成规则

每张表生成一条或多条 `schema_summary`：

内容建议包括：

- 表名
- 表用途
- 主键
- 外键
- 关键业务字段
- 状态/类型/分类字段的可选值
- 时间字段
- 金额字段
- 软删除字段

示例：

```text
表 public.orders:
- 主键: order_id
- 用户字段: user_id，关联 public.users.id
- 状态字段: status，可选值 [pending, paid, cancelled, refunded]
- 金额字段: pay_amount，默认值 0
- 创建时间: created_at，默认 CURRENT_TIMESTAMP
```

### 6.3 SQL 样例如何存

SQL 样例存到：

- `vanna_training_entries(entry_type=question_sql)`

关键字段：

- `question_text`
- `sql_text`
- `sql_explanation`
- `tables_read_json`
- `columns_read_json`
- `output_fields_json`
- `verification_result_json`

### 6.4 SQL 文档如何存

SQL 相关文档存到：

- `vanna_training_entries(entry_type=documentation)`

关键字段：

- `title`
- `doc_text`
- `business_domain`
- `system_name`
- `subject_area`
- `schema_name`
- `table_name`
- `tags_json`

---

## 七、模块目录设计

### `Text2SQLDatabase` 宿主模型补充字段

现有 `text2sql_databases` 也需要补两个字段，作为所有下游 SQL/Vanna 模块的宿主事实源：

| 字段 | 类型 | 说明 |
|---|---|---|
| `system_short` | String(64), index | 系统简称 |
| `env` | String(32), index | 环境标识 |

需要同步修改：

- `src/xagent/web/models/text2sql.py`
- `src/xagent/web/api/text2sql.py`
- `Text2SQLDatabase.to_dict()/from_dict()`
- 对应 Alembic 迁移

设计规则：

- `name` 仍然表示数据源显示名称
- `system_short` 表示业务系统短标识
- `env` 表示该数据源所处环境
- Vanna 不自行维护这两个字段的主数据，只在落库时做快照冗余

### 新增目录

- `src/xagent/core/vanna/`
- `src/xagent/web/api/vanna_sql.py`
- `src/xagent/web/models/vanna.py`
- `tests/core/vanna/`
- `tests/web/api/test_vanna_sql.py`

### 新增文件

- `src/xagent/core/vanna/errors.py`
- `src/xagent/core/vanna/contracts.py`
- `src/xagent/core/vanna/knowledge_base_service.py`
- `src/xagent/core/vanna/schema_harvest_service.py`
- `src/xagent/core/vanna/schema_summary_service.py`
- `src/xagent/core/vanna/train_service.py`
- `src/xagent/core/vanna/index_service.py`
- `src/xagent/core/vanna/retrieval_service.py`
- `src/xagent/core/vanna/prompt_builder.py`
- `src/xagent/core/vanna/ask_service.py`
- `src/xagent/core/tools/core/vanna_sql_tools.py`
- `src/xagent/migrations/versions/<revision>_add_vanna_module_tables.py`

### 修改文件

- `src/xagent/web/models/__init__.py`
- `src/xagent/web/models/database.py`
- `src/xagent/web/app.py`

---

## 八、核心流程设计

### 8.1 初始化知识库

1. 用户选择一个 `Text2SQLDatabase`
2. 创建默认知识库：
   - `kb_code = vanna.ds{datasource_id}.default`
3. 从数据源读取：
   - `system_short`
   - `env`
4. 写入 `vanna_knowledge_bases`

### 8.2 schema 采集流程

1. 创建 `vanna_schema_harvest_jobs`
2. 连接数据源读取：
   - `system_short`
   - `env`
   - tables
   - columns
   - comments
   - defaults
   - constraints
   - foreign keys
   - enum/check
   - sample values
3. 写入：
   - `vanna_schema_tables`
   - `vanna_schema_columns`
4. 由结构事实生成 `schema_summary`
5. 写入：
   - `vanna_training_entries(entry_type=schema_summary, lifecycle_status=candidate)`
6. 为 `schema_summary` 生成 chunk
7. 更新 harvest job 状态

### 8.3 `vn.train(...)` 流程

支持四种输入：

1. `question + sql`
2. `documentation`
3. `datasource_id + bootstrap_schema`
4. `sql` 单独输入
   - 先生成问题再落样例

规则：

- `question_sql`
  - 默认：
    - 人工录入 -> `published + verified`
    - auto_train -> `candidate + unverified`
- `documentation`
  - 默认 `published + verified`
- `schema_summary`
  - 默认 `candidate + unverified`

### 8.4 `vn.ask(...)` 流程

1. 校验 `datasource_id`
2. 获取知识库
3. 检索三类知识：
   - `question_sql`
   - `schema_summary`
   - `documentation`
4. 组装 Prompt
5. 调 LLM 生成 SQL
6. 写入 `vanna_ask_runs`
7. 若 `auto_run=false`
   - 返回 SQL 预览
8. 若 `auto_run=true`
   - 调现有 `execute_sql_query`
   - 接入现有 SQL 审批链
   - 写执行结果到 `vanna_ask_runs`
9. 若执行成功且允许沉淀
   - 写一条 `question_sql` 候选样例
   - 记录到 `auto_train_entry_id`

---

## 九、检索与 Prompt 设计

### 9.1 检索边界

只检索：

- 当前 `kb_id`
- 当前 `system_short`
- 当前 `env`
- `lifecycle_status = published`
- `quality_status != rejected`
- `embedding_model = 当前知识库默认 embedding_model`

### 9.2 分桶召回

分三桶：

1. `question_sql`
2. `schema_summary`
3. `documentation`

每桶单独 top-k，最后按固定顺序拼接。

默认建议：

- `top_k_sql = 8`
- `top_k_schema = 12`
- `top_k_doc = 6`

这部分直接借鉴 Vanna 的核心优点：

- 不把三类资产混在同一个召回池
- 每类资产单独控制召回条数

但要比 Vanna 多做两层治理：

1. 元数据过滤
   - 限定 `kb_id`
   - 限定 `system_short/env`
   - 限定 `lifecycle_status`
   - 限定 `quality_status`
   - 可选限定 `schema_name/table_name/business_domain`
2. 轻量重排
   - 相似度分数
   - 表命中数
   - 字段命中数
   - SQL 类型匹配
   - 发布时间/验证状态

### 9.3 pgvector 检索策略

Phase 1 检索 SQL 形态建议如下：

```sql
SELECT
  id,
  kb_id,
  entry_id,
  chunk_type,
  chunk_text,
  metadata_json,
  1 - (embedding_vector <=> :query_vector) AS similarity_score
FROM vanna_embedding_chunks
WHERE kb_id = :kb_id
  AND system_short = :system_short
  AND env = :env
  AND chunk_type = :chunk_type
  AND lifecycle_status = 'published'
  AND embedding_model = :embedding_model
ORDER BY embedding_vector <=> :query_vector
LIMIT :top_k;
```

说明：

- `<=>` 使用 cosine distance
- 相似度分数保存在内存里继续做二次排序
- 过滤条件先缩小候选集，再做向量排序

建议增加两个可配参数：

- `similarity_threshold`
- `max_context_tokens`

规则：

- 若命中分数低于阈值，则该桶可返回空
- 若最终上下文超长，则优先保留 `schema_summary` 和高质量 `question_sql`

### 9.4 Prompt 结构

建议结构：

1. `System`
   - 你是某 dialect 的 SQL 专家
   - 只能根据提供上下文回答
   - 不允许臆造表字段

2. `=== Relevant Question-SQL Examples`

3. `=== Relevant Schema Summary`

4. `=== Relevant Documentation`

5. `=== User Question`

输出要求：

- 只输出 SQL 或明确错误原因
- 优先生成只读 SQL
- 不输出解释性废话

---

## 十、API 设计

独立前缀：

- `/api/vanna`

建议接口：

1. `POST /api/vanna/kbs`
   - 创建知识库
2. `GET /api/vanna/kbs`
   - 列表
3. `GET /api/vanna/kbs/{kb_id}`
   - 详情
4. `POST /api/vanna/schema-harvest/preview`
   - 预览采集
5. `POST /api/vanna/schema-harvest/commit`
   - 提交采集
6. `GET /api/vanna/schema-tables`
   - 表级结构列表
7. `GET /api/vanna/schema-columns`
   - 字段级结构列表
8. `POST /api/vanna/train`
   - 手工训练
9. `GET /api/vanna/entries`
   - 训练条目列表
10. `POST /api/vanna/entries/{entry_id}/publish`
   - 发布候选条目
11. `POST /api/vanna/entries/{entry_id}/archive`
   - 归档条目
12. `POST /api/vanna/ask`
   - 生成 SQL 或自动执行
13. `GET /api/vanna/ask-runs`
   - ask 记录列表

---

## 十一、Tool 设计

新增：

- `src/xagent/core/tools/core/vanna_sql_tools.py`

暴露两个工具：

1. `vn_train`

参数建议：

- `datasource_id`
- `question`
- `sql`
- `documentation`
- `bootstrap_schema`
- `publish`

2. `vn_ask`

参数建议：

- `datasource_id`
- `question`
- `auto_run`

边界：

- `vn_train` 只负责知识沉淀
- `vn_ask` 负责检索、生成、可选执行
- 真正执行仍走现有 SQL 执行与审批基础设施

---

## 十二、数据库迁移设计

迁移文件：

- `src/xagent/migrations/versions/<revision>_add_vanna_module_tables.py`

需要创建：

1. `vanna_knowledge_bases`
2. `vanna_schema_harvest_jobs`
3. `vanna_schema_tables`
4. `vanna_schema_columns`
5. `vanna_training_entries`
6. `vanna_embedding_chunks`
7. `vanna_ask_runs`

还需要：

- 为 `text2sql_databases` 增加：
  - `system_short`
  - `env`
- 启用 `pgvector` 扩展
- 为 `vanna_embedding_chunks.embedding_vector` 建向量索引
- 明确向量维度跟随 `embedding_model` 配置

迁移要点：

1. `CREATE EXTENSION IF NOT EXISTS vector`
2. `embedding_vector` 使用原生 `vector(<dim>)`
3. 默认距离算子使用 `vector_cosine_ops`
4. 首版先保证正确性，再根据数据量选择：
   - `USING hnsw`
   - 或 `USING ivfflat`

关键索引：

- `kb_code`
- `datasource_id`
- `system_short`
- `env`
- `schema_name`
- `table_name`
- `column_name`
- `entry_type`
- `lifecycle_status`
- `quality_status`
- `chunk_type`
- `execution_status`
- `content_hash`
- `chunk_hash`
- `embedding_vector`

---

## 十七、为什么这里选 pgvector 而不是独立向量数据库

本期方案改为 `pgvector`，原因不是“向量数据库没价值”，而是当前 Xagent 这个模块更适合先做同库治理：

1. 元数据和向量天然强绑定
   - 一个 chunk 必须同时带上 `kb_id/entry_id/chunk_type/lifecycle_status/schema_name/table_name`
   - 放在 PostgreSQL 一张表里，过滤和治理最直接
2. 事务一致性更简单
   - `training_entry` 发布、归档、删除时，可以和 chunk 同事务更新
3. 运维复杂度低
   - 首版不引入额外服务，部署、备份、迁移都更简单
4. 当前规模足够
   - 典型单知识库的 schema 摘要、文档、样例数量不会一开始就大到必须独立向量库

后续如果出现以下情况，再考虑演进到独立向量数据库：

- chunk 数量达到千万级
- 需要多副本 ANN 横向扩展
- 需要混合检索、payload 过滤、分布式索引
- 需要专门的 rerank / hybrid 检索链路

---

## 十八、Vanna 向量存储实现分析

### 18.1 Vanna 的存储分层方式

Vanna 旧版核心思路很稳定：

- `sql`
- `ddl`
- `documentation`

三类知识分别存，不混在一个集合里。

这个设计是对的，因为：

- `question_sql` 负责 few-shot
- `ddl/schema` 负责结构约束
- `documentation` 负责业务语义

但 Vanna 旧版没有做“结构事实层”和“训练知识层”分离，所以它更像“训练语料仓”，不是“可治理的数据资产仓”。

### 18.2 Vanna 的 pgvector 实现做了什么

见：

- `D:/code/vanna/src/vanna/legacy/pgvector/pgvector.py`

它的实现特点：

1. 基于 `langchain_postgres.PGVector`
2. 创建 3 个 collection：
   - `sql`
   - `ddl`
   - `documentation`
3. `question + sql` 被序列化成一个 JSON 字符串后写入 `sql` collection
4. 检索时直接调用：
   - `similarity_search(query=question, k=n_results)`
5. 实际底表依赖 LangChain 的：
   - `langchain_pg_embedding`

这条路径的优点：

- 接入快
- 实现很薄
- 不需要自己维护向量 SQL

缺点也很明显：

- collection 语义粗
- 缺少 `kb_id/datasource_id/lifecycle_status` 这类业务过滤
- 没有显式相似度阈值
- 没有轻量 rerank
- 没有把 schema 字段事实结构化落库
- 无法很好支撑审核、发布、归档、版本治理

### 18.3 Vanna 的 Chroma / Qdrant 路径有什么值得借鉴

Chroma 版本值得借鉴的一点：

- 每个桶可以单独配置 `n_results_sql / n_results_ddl / n_results_documentation`

这说明 Vanna 作者已经意识到：

- SQL 样例、DDL、文档不应该共享同一个 top-k

Qdrant 版本值得借鉴的点：

- payload 比较自然
- `question_sql` 以结构化 payload 方式保存
- collection 建模更明确

但它们整体仍然偏“简单向量召回”，没有形成一套完整的治理模型。

### 18.4 Vanna 检索优化上做得不够的地方

Vanna 旧版 `vn.ask` 主路径里，检索层大体只有：

1. 生成 query embedding
2. 到三类 collection 各取 top-k
3. 拼进 prompt

缺少的关键能力有：

- datasource / kb 级隔离
- 已发布 / 候选 / 归档状态过滤
- 质量状态过滤
- 相似度阈值
- 命中后基于表名、字段名、业务域做重排
- SQL 执行反馈回流后的自动提纯
- 字段事实到 schema summary 的派生链路

所以对 Xagent 来说，真正该学 Vanna 的不是“它有多强的向量优化”，而是：

- 三桶分治
- `question_sql` 作为 few-shot 主资产
- `ddl/documentation` 作为补充上下文

真正需要补强的是：

- 资产治理
- 元数据过滤
- 轻量 rerank
- 审核发布链路
- ask 成功后的候选回流

---

## 十三、测试设计

### 单元测试

- `tests/web/test_vanna_models.py`
  - 七张表模型 round-trip
- `tests/web/api/test_text2sql.py`
  - 数据源 `system_short/env` 字段 round-trip
- `tests/core/vanna/test_schema_harvest_service.py`
  - schema 采集
- `tests/core/vanna/test_schema_summary_service.py`
  - 结构事实转摘要
- `tests/core/vanna/test_vanna_train_service.py`
  - 手工训练
- `tests/core/vanna/test_vanna_index_service.py`
  - chunk 生成
- `tests/core/vanna/test_vanna_retrieval_service.py`
  - 三路召回
- `tests/core/vanna/test_vanna_ask_service.py`
  - ask 预览、自动执行、候选沉淀

### API 测试

- `tests/web/api/test_vanna_sql.py`
  - 创建知识库
  - 采集 preview/commit
  - schema table/column 查询
  - train
  - publish/archive entry
  - ask preview
  - ask auto_run

### 集成测试

- 数据源 -> schema 采集 -> 生成 schema_summary -> 手工训练样例 -> ask -> auto_run -> auto_train candidate

---

## 十四、任务总览

1. 新增独立 Vanna 数据模型与迁移
2. 实现知识库服务与 schema 采集服务
3. 实现 schema_summary 生成与训练服务
4. 实现 chunk 索引、检索与 Prompt 组装
5. 实现 ask 服务
6. 暴露独立 API 与 tools
7. 测试、回归与文档收尾

---

### 任务 1: 新增独立数据模型与 Alembic 迁移

**Files:**
- Create: `src/xagent/web/models/vanna.py`
- Create: `src/xagent/migrations/versions/<revision>_add_vanna_module_tables.py`
- Modify: `src/xagent/web/models/text2sql.py`
- Modify: `src/xagent/web/api/text2sql.py`
- Modify: `src/xagent/web/models/__init__.py`
- Modify: `src/xagent/web/models/database.py`
- Test: `tests/web/test_vanna_models.py`
- Test: `tests/web/api/test_text2sql.py`

- [ ] **Step 1: 编写模型测试**

覆盖：

- 知识库创建
- schema_harvest_job 状态
- table/column 结构事实落库
- training_entry 三种类型约束
- ask_run 执行状态 round-trip
- `Text2SQLDatabase.system_short/env` 落库与序列化

- [ ] **Step 2: 实现 SQLAlchemy 模型**

- [ ] **Step 3: 注册模型并更新数据库初始化**

- [ ] **Step 4: 编写 Alembic 迁移**

- [ ] **Step 5: 运行测试**

Run:
```bash
pytest tests/web/test_vanna_models.py -q
```

- [ ] **Step 6: 提交**

```bash
git add src/xagent/web/models/vanna.py src/xagent/web/models/text2sql.py src/xagent/web/api/text2sql.py src/xagent/web/models/__init__.py src/xagent/web/models/database.py src/xagent/migrations/versions/<revision>_add_vanna_module_tables.py tests/web/test_vanna_models.py tests/web/api/test_text2sql.py
git commit -m "feat: add vanna tables and datasource system metadata"
```

### 任务 2: 实现知识库服务与 schema 采集服务

**Files:**
- Create: `src/xagent/core/vanna/errors.py`
- Create: `src/xagent/core/vanna/contracts.py`
- Create: `src/xagent/core/vanna/knowledge_base_service.py`
- Create: `src/xagent/core/vanna/schema_harvest_service.py`
- Test: `tests/core/vanna/test_schema_harvest_service.py`

- [ ] **Step 1: 编写 schema 采集测试**

覆盖：

- 创建默认知识库
- 从 `Text2SQLDatabase` 读取连接配置
- 读取并下沉 `system_short/env`
- 采集表级 DDL 与表注释
- 采集字段注释、默认值、取值方式

- [ ] **Step 2: 实现知识库服务**

能力：

- `get_or_create_default_kb`
- `list_kbs`
- `get_kb`

- [ ] **Step 3: 实现 schema 采集服务**

能力：

- `preview_harvest`
- `commit_harvest`
- `load_table_facts`
- `load_column_facts`

- [ ] **Step 4: 运行测试**

Run:
```bash
pytest tests/core/vanna/test_schema_harvest_service.py -q
```

- [ ] **Step 5: 提交**

```bash
git add src/xagent/core/vanna/errors.py src/xagent/core/vanna/contracts.py src/xagent/core/vanna/knowledge_base_service.py src/xagent/core/vanna/schema_harvest_service.py tests/core/vanna/test_schema_harvest_service.py
git commit -m "feat: add vanna knowledge base and schema harvest services"
```

### 任务 3: 实现 schema_summary 生成与训练服务

**Files:**
- Create: `src/xagent/core/vanna/schema_summary_service.py`
- Create: `src/xagent/core/vanna/train_service.py`
- Test: `tests/core/vanna/test_schema_summary_service.py`
- Test: `tests/core/vanna/test_vanna_train_service.py`

- [ ] **Step 1: 编写 schema_summary 测试**

覆盖：

- 从表级字段事实生成摘要
- 状态字段枚举值写入摘要
- 默认值和外键关系写入摘要

- [ ] **Step 2: 编写 train 服务测试**

覆盖：

- 手工 `question+sql`
- 手工 `documentation`
- bootstrap 生成 `schema_summary`
- auto_train 候选状态

- [ ] **Step 3: 实现 schema_summary 服务**

- [ ] **Step 4: 实现 train 服务**

- [ ] **Step 5: 运行测试**

Run:
```bash
pytest tests/core/vanna/test_schema_summary_service.py tests/core/vanna/test_vanna_train_service.py -q
```

- [ ] **Step 6: 提交**

```bash
git add src/xagent/core/vanna/schema_summary_service.py src/xagent/core/vanna/train_service.py tests/core/vanna/test_schema_summary_service.py tests/core/vanna/test_vanna_train_service.py
git commit -m "feat: add vanna schema summary and train services"
```

### 任务 4: 实现索引、检索与 ask 服务

**Files:**
- Create: `src/xagent/core/vanna/index_service.py`
- Create: `src/xagent/core/vanna/retrieval_service.py`
- Create: `src/xagent/core/vanna/prompt_builder.py`
- Create: `src/xagent/core/vanna/ask_service.py`
- Test: `tests/core/vanna/test_vanna_index_service.py`
- Test: `tests/core/vanna/test_vanna_retrieval_service.py`
- Test: `tests/core/vanna/test_vanna_ask_service.py`

- [ ] **Step 1: 编写 index 测试**

覆盖：

- `question_sql` 生成 `question_sql_pair` chunk
- `schema_summary` 生成 `schema_table_summary` chunk
- `documentation` 生成 `documentation` chunk

- [ ] **Step 2: 编写 retrieval 测试**

覆盖：

- 分桶召回
- 仅召回 `published`
- datasource 隔离

- [ ] **Step 3: 编写 ask 服务测试**

覆盖：

- ask preview
- ask auto_run
- waiting_approval 映射
- auto_train 候选沉淀

- [ ] **Step 4: 实现 index、retrieval、prompt_builder、ask 服务**

- [ ] **Step 5: 运行测试**

Run:
```bash
pytest tests/core/vanna/test_vanna_index_service.py tests/core/vanna/test_vanna_retrieval_service.py tests/core/vanna/test_vanna_ask_service.py -q
```

- [ ] **Step 6: 提交**

```bash
git add src/xagent/core/vanna/index_service.py src/xagent/core/vanna/retrieval_service.py src/xagent/core/vanna/prompt_builder.py src/xagent/core/vanna/ask_service.py tests/core/vanna/test_vanna_index_service.py tests/core/vanna/test_vanna_retrieval_service.py tests/core/vanna/test_vanna_ask_service.py
git commit -m "feat: add vanna indexing retrieval and ask services"
```

### 任务 5: 暴露独立 API 与 tools

**Files:**
- Create: `src/xagent/web/api/vanna_sql.py`
- Create: `src/xagent/core/tools/core/vanna_sql_tools.py`
- Modify: `src/xagent/web/app.py`
- Test: `tests/web/api/test_vanna_sql.py`

- [ ] **Step 1: 编写 API 测试**

覆盖：

- 创建知识库
- schema harvest preview/commit
- schema tables/columns list
- train
- publish/archive entry
- ask preview
- ask auto_run

- [ ] **Step 2: 实现 API**

- [ ] **Step 3: 实现 tools**

- [ ] **Step 4: 注册 router**

- [ ] **Step 5: 运行测试**

Run:
```bash
pytest tests/web/api/test_vanna_sql.py -q
```

- [ ] **Step 6: 提交**

```bash
git add src/xagent/web/api/vanna_sql.py src/xagent/core/tools/core/vanna_sql_tools.py src/xagent/web/app.py tests/web/api/test_vanna_sql.py
git commit -m "feat: expose vanna sql api and tools"
```

### 任务 6: 联调、回归与文档收尾

**Files:**
- Modify: `doc/xagentvanna实施计划.md`
- Modify: `README.md`

- [ ] **Step 1: 端到端联调**

场景：

1. 新增数据源
2. 初始化知识库
3. schema 采集
4. 查看表和字段事实
5. 生成 schema_summary
6. 手工训练 question+sql
7. ask preview
8. ask auto_run
9. ask 成功沉淀 candidate
10. 发布 candidate 后再次 ask

- [ ] **Step 2: 运行目标测试集**

Run:
```bash
pytest tests/web/test_vanna_models.py tests/core/vanna/test_schema_harvest_service.py tests/core/vanna/test_schema_summary_service.py tests/core/vanna/test_vanna_train_service.py tests/core/vanna/test_vanna_index_service.py tests/core/vanna/test_vanna_retrieval_service.py tests/core/vanna/test_vanna_ask_service.py tests/web/api/test_vanna_sql.py -q
```

- [ ] **Step 3: 更新文档**

- [ ] **Step 4: 提交**

```bash
git add doc/xagentvanna实施计划.md README.md
git commit -m "docs: finalize xagent vanna implementation plan"
```

---

## 十五、阶段验收标准

### 功能验收

- 用户可在一个数据源上初始化独立 Vanna 知识库
- 系统可采集表级和字段级结构事实
- 系统可查询字段注释、默认值、取值方式和枚举值
- 系统可生成并管理 `schema_summary`
- 用户可手工训练 `question_sql` 和 `documentation`
- 用户可通过 `vn.ask` 获得 SQL 预览
- 用户可通过 `vn.ask(auto_run=true)` 执行 SQL
- ask 成功后能沉淀候选样例

### 结构验收

- 不依赖 `datamake_sql_asset`
- 独立模型、独立 API、独立 services、独立 tests 完整落地
- 只复用：
  - `Text2SQLDatabase`
  - OpenAI-compatible LLM
  - `execute_sql_query`
  - SQL 审批链

### 风险控制验收

- ask 不默认自动执行
- 自动执行必须显式 `auto_run=true`
- 自动执行继续走现有审批机制
- auto_train 默认只生成 `candidate`

---

## 十六、推荐实施顺序

1. 模型和迁移
2. schema 采集
3. schema_summary 生成
4. train
5. index 和 retrieval
6. ask
7. API 和 tools
8. 联调和回归

理由：

- 先把结构事实层建稳
- 再把训练知识层建稳
- 最后接入生成和执行链路，避免返工
