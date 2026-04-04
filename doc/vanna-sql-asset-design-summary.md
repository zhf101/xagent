# Vanna SQL Asset 设计总结

## 1. 背景与问题

当前仓库里已经有两类与 SQL 相关的核心概念：

- `vanna.ask`
  - 表示一次即时的 Text2SQL 生成与可选执行过程
  - 结果落在 `VannaAskRun`
- `vanna.train`
  - 表示一条供召回和生成使用的知识条目
  - 结果落在 `VannaTrainingEntry`

但“一个已经固定下来、下次还要继续复用的 SQL”并不适合只表达成这两者之一：

- 它不是一次性 ask 结果
- 它也不只是训练语料
- 它需要被快速检索、稳定复用、参数化执行、版本管理和运行审计

因此需要引入第三类强概念：

- `SQL Asset`
  - 表示可发布、可版本化、可参数化、可直接执行的正式 SQL 资产


## 2. 三层概念边界

建议把体系明确拆成三层：

- `ask`
  - 负责即时生成
  - 产出的是一次运行事实
- `train entry`
  - 负责知识沉淀与检索增强
  - 产出的是训练知识条目
- `sql asset`
  - 负责正式复用
  - 产出的是可执行、可管理的 SQL 资产

一句话总结：

- `ask` 负责发现
- `train` 负责记忆
- `asset` 负责复用


## 3. 与现有 Vanna 流程的区别

### 3.1 原有 `vanna.ask`

现有 ask 流程是：

1. 按知识库做召回
2. 组装 prompt
3. 让 LLM 直接生成 SQL
4. 可选执行
5. 可选自动写入一条 `question_sql` 训练条目

它的核心目标是：

- 生成一条当前问题可用的 SQL

它的主要特点是：

- 偏即时生成
- 输出是一次性 `generated_sql`
- 不天然强调复用和参数契约

### 3.2 新的 SQL Asset 流程

SQL Asset 的目标不是“再生成一次 SQL”，而是：

- 快速命中已有资产
- 给资产补齐本次执行参数
- 编译成真正可执行的 SQL
- 留下稳定可审计的运行记录

它的核心目标是：

- 稳定复用
- 参数装配
- 版本治理
- 执行审计


## 4. 与现有表的关系

### 4.1 现有表继续保留

- `VannaKnowledgeBase`
  - 表示知识库和检索边界
- `VannaTrainingEntry`
  - 表示训练条目
- `VannaAskRun`
  - 表示 ask 的运行事实

### 4.2 新增表建议

建议新增三张表：

1. `vanna_sql_assets`
   - 资产头
2. `vanna_sql_asset_versions`
   - 资产版本
3. `vanna_sql_asset_runs`
   - 资产执行事实

### 4.3 关系设计

- `sql_asset.kb_id -> vanna_knowledge_bases.id`
- `sql_asset.datasource_id -> text2sql_databases.id`
- `sql_asset.origin_ask_run_id -> vanna_ask_runs.id`
- `sql_asset.origin_training_entry_id -> vanna_training_entries.id`
- `sql_asset_version.asset_id -> sql_asset.id`
- `sql_asset_run.asset_id -> sql_asset.id`
- `sql_asset_run.asset_version_id -> sql_asset_version.id`

语义上：

- `ask_run` 代表资产最初来源于哪次即时生成
- `training_entry` 代表资产对应沉淀过哪些训练知识
- `sql_asset` 代表正式复用对象


## 5. 新表设计摘要

### 5.1 `vanna_sql_assets`

职责：

- 表达“这是一项什么 SQL 能力”

建议字段：

- `id`
- `kb_id`
- `datasource_id`
- `asset_code`
- `name`
- `description`
- `intent_summary`
- `asset_kind`
- `status`
- `system_short`
- `env`
- `match_keywords_json`
- `match_examples_json`
- `owner_user_id`
- `owner_user_name`
- `current_version_id`
- `origin_ask_run_id`
- `origin_training_entry_id`
- `created_at`
- `updated_at`

### 5.2 `vanna_sql_asset_versions`

职责：

- 表达“这项 SQL 资产当前这一版如何执行”

建议字段：

- `id`
- `asset_id`
- `version_no`
- `version_label`
- `template_sql`
- `parameter_schema_json`
- `render_config_json`
- `statement_kind`
- `tables_read_json`
- `columns_read_json`
- `output_fields_json`
- `verification_result_json`
- `quality_status`
- `is_published`
- `published_at`
- `created_by`
- `created_at`

### 5.3 `vanna_sql_asset_runs`

职责：

- 表达“这次执行命中了哪条资产、绑定了什么参数、实际执行了什么 SQL”

建议字段：

- `id`
- `asset_id`
- `asset_version_id`
- `kb_id`
- `datasource_id`
- `task_id`
- `question_text`
- `resolved_by`
- `binding_plan_json`
- `bound_params_json`
- `compiled_sql`
- `execution_status`
- `execution_result_json`
- `approval_status`
- `create_user_id`
- `create_user_name`
- `created_at`


## 6. 为什么不能直接复用 `VannaTrainingEntry`

虽然 `VannaTrainingEntry` 已经有一些相似字段，比如：

- `question_text`
- `sql_text`
- `variables_json`
- `tables_read_json`
- `columns_read_json`
- `output_fields_json`
- `verification_result_json`

但它本质上仍然是训练知识，不是正式资产，原因有：

- 缺少稳定主键语义，如 `asset_code`
- 缺少版本化语义
- 缺少正式发布语义
- 缺少参数契约
- 缺少资产执行事实表
- 缺少资产优先命中逻辑

结论：

- `question_sql` 可以继续保留为训练知识
- 但不能替代 `sql asset`


## 7. 参数如何表达

不要把固定 SQL 存成每次都要重写的一段纯文本，也不要只把参数藏在自然语言问题里。

建议采用：

- `template_sql`
- `parameter_schema_json`

### 7.1 模板 SQL

示例：

```sql
select
  dt,
  region,
  sum(amount) as revenue
from dwd_order
where dt >= {{ start_date }}
  and dt < {{ end_date }}
  {% if region_list %}
  and region in {{ region_list }}
  {% endif %}
group by dt, region
```

### 7.2 参数 Schema

示例：

```json
[
  {
    "name": "start_date",
    "label": "开始日期",
    "data_type": "date",
    "required": true,
    "source_policy": "user_or_context",
    "description": "开始日期，含当日",
    "default_value": null
  },
  {
    "name": "end_date",
    "label": "结束日期",
    "data_type": "date",
    "required": true,
    "source_policy": "derived",
    "description": "结束日期，不含当日",
    "default_value": null,
    "derive_from": {
      "kind": "range_end_exclusive",
      "ref": "start_date"
    }
  },
  {
    "name": "region_list",
    "label": "区域列表",
    "data_type": "string_array",
    "required": false,
    "source_policy": "user_or_default",
    "description": "区域过滤列表",
    "default_value": []
  }
]
```


## 8. 参数来源策略

建议参数值来源显式记录，不要只得到最后结果。

推荐来源优先级：

1. `explicit_user`
2. `task_context`
3. `system_runtime`
4. `default_value`
5. `llm_inferred`

最终应在 `binding_plan_json` 中保留来源说明，例如：

```json
{
  "start_date": {
    "value": "2026-04-06",
    "source": "llm_inferred"
  },
  "end_date": {
    "value": "2026-04-13",
    "source": "derived"
  }
}
```


## 9. 参数装配与执行原则

### 9.1 LLM 不负责重写固定 SQL

在命中 SQL Asset 后，LLM 不再负责输出完整 SQL，而是负责：

- 选择资产
- 识别参数
- 补全参数
- 标记缺失参数

建议让 LLM 输出：

```json
{
  "asset_code": "sales.daily_revenue_by_region",
  "bindings": {
    "start_date": "2026-04-06",
    "end_date": "2026-04-13",
    "region_list": ["east", "north"]
  },
  "missing_params": [],
  "assumptions": ["本周按自然周处理"]
}
```

### 9.2 不允许裸字符串替换

运行时必须经过：

1. 选择资产版本
2. 参数收集
3. 参数校验
4. 模板编译
5. SQL 执行

真正执行前应得到：

- `compiled_sql`
- `bound_params`

而不是一条纯字符串拼出来的 SQL。


## 10. 建议的运行模式

### 10.1 `asset-first`

主路径建议如下：

1. 用户提问
2. 优先检索 SQL Asset
3. 如果命中
   - 做参数装配
   - 模板编译
   - 执行
   - 写 `vanna_sql_asset_runs`

### 10.2 `ask-fallback`

如果资产未命中：

1. 走现有 `vanna.ask`
2. 生成一次 SQL
3. 用户确认可沉淀
4. 提升为 `sql asset`
5. 可选同步写一条 `question_sql` 训练条目

一句话：

- 先资产复用
- 再 ask 兜底


## 11. API 设计摘要

建议新增路由前缀：

- `/api/vanna/assets`

### 11.1 资产管理

- `POST /api/vanna/assets`
- `GET /api/vanna/assets`
- `GET /api/vanna/assets/{asset_id}`
- `POST /api/vanna/assets/{asset_id}/versions`
- `GET /api/vanna/assets/{asset_id}/versions`
- `POST /api/vanna/assets/{asset_id}/publish`

### 11.2 资产命中与执行

- `POST /api/vanna/assets/resolve`
- `POST /api/vanna/assets/{asset_id}/bind`
- `POST /api/vanna/assets/{asset_id}/execute`
- `GET /api/vanna/assets/{asset_id}/runs`

### 11.3 ask / train 提升为资产

建议在现有 `vanna` 路由下补两个入口：

- `POST /api/vanna/ask-runs/{ask_run_id}/promote`
- `POST /api/vanna/entries/{entry_id}/promote`


## 12. 服务拆分建议

建议新增以下 service：

- `SqlAssetService`
  - 资产 CRUD、版本、发布
- `SqlAssetResolver`
  - 资产检索
- `SqlAssetBindingService`
  - 参数提取、推导、校验
- `SqlTemplateCompiler`
  - 模板转执行 SQL
- `SqlAssetExecutionService`
  - 执行并落 run

另外建议增加统一编排入口：

- `QueryService`

职责：

- 优先 `asset-first`
- 失败时 `ask-fallback`


## 13. 推荐实施顺序

为了控制复杂度，建议按以下顺序落地：

1. 新增三张表和 ORM 模型
2. 支持手工创建 SQL Asset
3. 支持手工创建版本并发布
4. 支持显式参数执行
5. 支持 ask-run promote 为资产
6. 再加入 LLM 自动补参
7. 最后做统一 `asset-first / ask-fallback` 编排


## 14. 最终结论

这次设计的关键不是扩展 `ask` 或 `train`，而是补上正式资产层。

最终语义应该固定为：

- `ask`
  - 负责即时生成
- `train`
  - 负责知识召回
- `sql asset`
  - 负责正式复用
- `binding`
  - 负责把资产变成一次真正可执行的 SQL

因此，“一个已经固定下来、以后还要继续用的 SQL”，应表达为：

- `SQL Asset`

而不是单纯的：

- `ask pair`
- 或 `question_sql` 训练条目


## 15. 实施稿范围

在现阶段，建议把实现稿拆成四个交付物：

1. Alembic migration
2. ORM 模型
3. API schema 与 router
4. service 编排

目标不是一次把全部智能能力做完，而是先把“正式 SQL 资产”的持久化边界和调用边界立住。


## 16. Alembic 迁移设计

建议新增一个 migration，例如：

- `src/xagent/migrations/versions/2026040x_add_vanna_sql_assets.py`

### 16.1 `vanna_sql_assets`

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer` | 主键 |
| `kb_id` | `Integer` | 关联知识库 |
| `datasource_id` | `Integer` | 关联数据源 |
| `asset_code` | `String(255)` | 资产稳定编码，全局唯一 |
| `name` | `String(255)` | 资产名称 |
| `description` | `Text` | 资产描述 |
| `intent_summary` | `Text` | 用途摘要 |
| `asset_kind` | `String(32)` | 资产类型，如 `query/report` |
| `status` | `String(32)` | `draft/published/deprecated/archived` |
| `system_short` | `String(64)` | 系统简称 |
| `env` | `String(32)` | 环境 |
| `match_keywords_json` | `JSON` | 检索关键词 |
| `match_examples_json` | `JSON` | 命中示例 |
| `owner_user_id` | `Integer` | 所有者 |
| `owner_user_name` | `String(255)` | 所有者用户名 |
| `current_version_id` | `Integer` | 当前发布版本 ID |
| `origin_ask_run_id` | `Integer` | 来源 ask run |
| `origin_training_entry_id` | `Integer` | 来源训练条目 |
| `created_at` | `DateTime` | 创建时间 |
| `updated_at` | `DateTime` | 更新时间 |

推荐索引：

- `asset_code`
- `(kb_id, status)`
- `(datasource_id, status)`
- `(system_short, env, status)`

### 16.2 `vanna_sql_asset_versions`

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer` | 主键 |
| `asset_id` | `Integer` | 归属资产 |
| `version_no` | `Integer` | 版本号，自增 |
| `version_label` | `String(64)` | 版本标签 |
| `template_sql` | `Text` | 逻辑 SQL 模板 |
| `parameter_schema_json` | `JSON` | 参数契约 |
| `render_config_json` | `JSON` | 渲染/编译配置 |
| `statement_kind` | `String(32)` | 初期只允许 `SELECT` |
| `tables_read_json` | `JSON` | 读取表集合 |
| `columns_read_json` | `JSON` | 读取列集合 |
| `output_fields_json` | `JSON` | 输出字段集合 |
| `verification_result_json` | `JSON` | 验证结果 |
| `quality_status` | `String(32)` | `unverified/verified/rejected` |
| `is_published` | `Boolean` | 是否已发布 |
| `published_at` | `DateTime` | 发布时间 |
| `created_by` | `String(255)` | 创建人 |
| `created_at` | `DateTime` | 创建时间 |

约束建议：

- `(asset_id, version_no)` 唯一

### 16.3 `vanna_sql_asset_runs`

建议字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `Integer` | 主键 |
| `asset_id` | `Integer` | 命中的资产 |
| `asset_version_id` | `Integer` | 命中的资产版本 |
| `kb_id` | `Integer` | 归属知识库 |
| `datasource_id` | `Integer` | 归属数据源 |
| `task_id` | `Integer` | 关联任务 |
| `question_text` | `Text` | 原始问题 |
| `resolved_by` | `String(32)` | `asset_search/ask_promote/manual` |
| `binding_plan_json` | `JSON` | 参数来源与装配计划 |
| `bound_params_json` | `JSON` | 最终绑定参数 |
| `compiled_sql` | `Text` | 最终可执行 SQL |
| `execution_status` | `String(32)` | `bound/executed/failed/waiting_approval` |
| `execution_result_json` | `JSON` | 执行结果 |
| `approval_status` | `String(32)` | 审批状态 |
| `create_user_id` | `Integer` | 执行人 |
| `create_user_name` | `String(255)` | 执行用户名 |
| `created_at` | `DateTime` | 创建时间 |


## 17. ORM 模型设计

建议继续放在：

- `src/xagent/web/models/vanna.py`

原因：

- 这些表仍然属于 Vanna 语义域
- 和 `VannaKnowledgeBase`、`VannaTrainingEntry`、`VannaAskRun` 紧密关联
- 当前仓库的 Vanna 宿主表已经集中在这一文件中

### 17.1 推荐新增枚举

- `VannaSqlAssetStatus`
  - `draft`
  - `published`
  - `deprecated`
  - `archived`
- `VannaSqlAssetQualityStatus`
  - `unverified`
  - `verified`
  - `rejected`
- `VannaSqlAssetRunStatus`
  - `bound`
  - `executed`
  - `failed`
  - `waiting_approval`

### 17.2 推荐模型

- `VannaSqlAsset`
- `VannaSqlAssetVersion`
- `VannaSqlAssetRun`

其中：

- `VannaSqlAsset` 负责资产头
- `VannaSqlAssetVersion` 负责版本体
- `VannaSqlAssetRun` 负责执行事实

此外需要在：

- `src/xagent/web/models/__init__.py`

中补充导出，保证建表和序列化能被统一发现。


## 18. API 设计草案

建议新增一个独立 router：

- `src/xagent/web/api/vanna_assets.py`

路由前缀：

- `/api/vanna/assets`

### 18.1 资产管理

- `POST /api/vanna/assets`
  - 创建资产头
- `GET /api/vanna/assets`
  - 资产列表
- `GET /api/vanna/assets/{asset_id}`
  - 资产详情
- `POST /api/vanna/assets/{asset_id}/versions`
  - 新增版本
- `GET /api/vanna/assets/{asset_id}/versions`
  - 版本列表
- `POST /api/vanna/assets/{asset_id}/publish`
  - 发布指定版本

### 18.2 资产检索与执行

- `POST /api/vanna/assets/resolve`
  - 根据问题搜索资产候选
- `POST /api/vanna/assets/{asset_id}/bind`
  - 做参数装配，但不执行
- `POST /api/vanna/assets/{asset_id}/execute`
  - 装配并执行
- `GET /api/vanna/assets/{asset_id}/runs`
  - 查看资产执行记录

### 18.3 ask/train 提升为资产

建议继续复用现有 `vanna` 路由，新增：

- `POST /api/vanna/ask-runs/{ask_run_id}/promote`
- `POST /api/vanna/entries/{entry_id}/promote`

语义：

- 某次 ask 生成的 SQL 被确认后，可以提升为 SQL Asset
- 某条训练 entry 被认为已经稳定，也可以提升为 SQL Asset


## 19. Request / Response 结构建议

### 19.1 创建资产

请求体建议：

```json
{
  "datasource_id": 12,
  "kb_id": 5,
  "asset_code": "sales.daily_revenue_by_region",
  "name": "按区域统计日营收",
  "description": "按日期和区域汇总营收",
  "intent_summary": "用于区域营收看板",
  "asset_kind": "query",
  "match_keywords": ["营收", "收入", "区域", "日报"],
  "match_examples": [
    "查一下本周各区域营收",
    "按大区统计最近7天收入"
  ]
}
```

### 19.2 创建版本

请求体建议：

```json
{
  "template_sql": "select dt, region, sum(amount) as revenue from dwd_order where dt >= {{ start_date }} and dt < {{ end_date }}",
  "parameter_schema_json": [
    {
      "name": "start_date",
      "data_type": "date",
      "required": true,
      "source_policy": "user_or_context"
    }
  ],
  "render_config_json": {
    "param_style": "named",
    "array_strategy": "expand_in_clause"
  },
  "statement_kind": "SELECT",
  "tables_read_json": ["dwd_order"],
  "columns_read_json": ["dt", "region", "amount"],
  "output_fields_json": ["dt", "region", "revenue"],
  "version_label": "v1"
}
```

### 19.3 资产命中

请求体建议：

```json
{
  "datasource_id": 12,
  "kb_id": 5,
  "question": "查本周各区域营收",
  "top_k": 5
}
```

返回建议：

```json
{
  "data": {
    "matches": [
      {
        "asset_id": 101,
        "asset_code": "sales.daily_revenue_by_region",
        "name": "按区域统计日营收",
        "score": 0.93,
        "reason": "keyword_match:name/example",
        "current_version_id": 1001
      }
    ]
  }
}
```

### 19.4 参数装配

请求体建议：

```json
{
  "question": "查本周各区域营收",
  "explicit_params": {},
  "context": {
    "timezone": "Asia/Shanghai"
  }
}
```

返回建议：

```json
{
  "data": {
    "asset_id": 101,
    "asset_version_id": 1001,
    "binding_plan": {
      "start_date": {
        "value": "2026-04-06",
        "source": "llm_inferred"
      },
      "end_date": {
        "value": "2026-04-13",
        "source": "derived"
      }
    },
    "bound_params": {
      "start_date": "2026-04-06",
      "end_date": "2026-04-13"
    },
    "missing_params": [],
    "compiled_sql": "select ... where dt >= :start_date and dt < :end_date",
    "assumptions": ["本周按自然周处理"]
  }
}
```


## 20. Service 分层建议

建议新增目录：

- `src/xagent/core/vanna/sql_assets/`

建议拆成以下模块：

### 20.1 `service.py`

职责：

- 资产 CRUD
- 版本创建
- 发布版本
- ask/train promote

### 20.2 `resolver.py`

职责：

- 基于 `asset_code/name/keywords/examples`
- 先实现规则匹配
- 后续再加 embedding 检索

### 20.3 `binding.py`

职责：

- 归一化显式参数
- 注入系统参数
- 派生默认参数
- 可选调用 LLM 做缺失参数补齐
- 输出 `binding_plan` 和 `bound_params`

### 20.4 `compiler.py`

职责：

- 把逻辑模板编译成最终 SQL
- 统一输出：
  - `compiled_sql`
  - `bound_params`

### 20.5 `executor.py`

职责：

- 绑定
- 编译
- 调用底层 SQL 执行器
- 写 `VannaSqlAssetRun`

### 20.6 `query_service.py`

职责：

- 实现统一编排
- 优先 `asset-first`
- 失败时 `ask-fallback`


## 21. asset-first / ask-fallback 编排

建议统一入口的时序如下：

### 21.1 `asset-first`

1. 用户输入问题
2. `SqlAssetResolver` 搜索资产候选
3. 命中资产后读取当前发布版本
4. `SqlAssetBindingService` 生成参数绑定结果
5. `SqlTemplateCompiler` 编译模板
6. `SqlAssetExecutionService` 执行 SQL
7. 写 `vanna_sql_asset_runs`

### 21.2 `ask-fallback`

1. 资产未命中
2. 调用现有 `AskService`
3. 返回 ask 结果
4. 用户确认后触发 promote
5. 生成 `sql_asset + version`
6. 可选同步一条 `VannaTrainingEntry(question_sql)`

建议统一返回 envelope：

```json
{
  "data": {
    "mode": "asset_hit",
    "asset_run_id": 9001,
    "compiled_sql": "...",
    "bound_params": {},
    "execution_result": {}
  }
}
```

或：

```json
{
  "data": {
    "mode": "ask_generated",
    "ask_run_id": 88,
    "generated_sql": "select ..."
  }
}
```


## 22. 参数契约与编译规则

### 22.1 参数类型建议

建议初版只支持：

- `string`
- `int`
- `float`
- `boolean`
- `date`
- `datetime`
- `string_array`

### 22.2 参数策略建议

建议支持：

- `required`
- `default_value`
- `source_policy`
- `derive_from`
- `validation`

### 22.3 渲染规则建议

不要直接做字符串替换。

建议采用两阶段：

1. 逻辑模板渲染
2. 驱动参数编译

`render_config_json` 建议支持：

```json
{
  "dialect": "postgresql",
  "param_style": "named",
  "array_strategy": "expand_in_clause",
  "strict_missing_params": true,
  "allow_unused_params": false
}
```

最终执行对象应是：

```json
{
  "compiled_sql": "select ... where dt >= :start_date and region in (:region_0, :region_1)",
  "bound_params": {
    "start_date": "2026-04-06",
    "region_0": "east",
    "region_1": "north"
  }
}
```


## 23. LLM 在资产模式下的职责

在资产命中模式下，LLM 不再负责生成完整 SQL，而是负责：

- 理解问题
- 识别参数
- 填充参数
- 标出缺失参数
- 记录推断假设

建议输出格式：

```json
{
  "bindings": {
    "start_date": "2026-04-06",
    "end_date": "2026-04-13"
  },
  "missing_params": [],
  "assumptions": [
    "本周按自然周处理"
  ]
}
```

原则：

- LLM 负责“补值”
- 不负责“重写固定 SQL”


## 24. 推荐开发顺序

建议把实施分成三期：

### 第一期：立资产边界

目标：

- 建表
- 建模型
- 支持手工创建资产和版本
- 支持发布版本

### 第二期：立执行边界

目标：

- 支持显式参数绑定
- 支持模板编译
- 支持执行资产并记录 run

### 第三期：立智能边界

目标：

- 支持资产检索
- 支持 LLM 自动补参
- 支持 ask promote
- 支持统一 `asset-first / ask-fallback`


## 25. 当前建议的最终落点

当前最值得先实现的，不是“让 ask 更聪明”，而是：

- 把 `SQL Asset` 作为正式一等实体先立起来

实现上的一句话落点：

- 先有资产表
- 再有版本表
- 再有运行表
- 再有参数契约
- 最后再让 LLM 来帮资产填参数

这样能保证系统从第一天开始就有稳定的沉淀边界，而不是把所有“固定 SQL”继续混在 ask 和 train 里。
