  把现有体系拆成三层：

  - ask：一次即时生成
  - train entry：一条检索知识
  - sql asset：一个可复用、可版本化、可参数化、可执行的正式 SQL 资产

  在你这个场景里，主路径应该是：

  1. 先查 sql asset
  2. 命中后做参数装配
  3. 未命中再走 vanna.ask
  4. ask 成功后可“提升为 asset”

  新表设计

  1. vanna_sql_assets
     用途：资产头，表达“这是什么能力”

  建议字段：

  - id
  - kb_id
  - datasource_id
  - asset_code
    例：sales.daily_revenue_by_region
  - name
  - description
  - intent_summary
  - system_short
  - env
  - status
    值：draft/published/deprecated/archived
  - asset_kind
    值：query/report/metric_lookup/detail_lookup
  - match_keywords_json
  - match_examples_json
  - owner_user_id
  - owner_user_name
  - current_version_id
  - origin_ask_run_id
  - origin_training_entry_id
  - created_at
  - updated_at

  2. vanna_sql_asset_versions
     用途：版本体，表达“当前这一版怎么执行”

  建议字段：

  - id
  - asset_id
  - version_no
  - version_label
  - template_sql
  - parameter_schema_json
  - render_config_json
  - statement_kind
    先只允许 SELECT
  - tables_read_json
  - columns_read_json
  - output_fields_json
  - verification_result_json
  - quality_status
    值：unverified/verified/rejected
  - published_at
  - created_by
  - created_at

  3. vanna_sql_asset_runs
     用途：执行事实，表达“这次怎么命中的、怎么绑定的、执行结果如何”

  建议字段：

  - id
  - asset_id
  - asset_version_id
  - kb_id
  - datasource_id
  - task_id
  - question_text
  - resolved_by
    值：asset_search/ask_promote/manual
  - binding_plan_json
  - bound_params_json
  - compiled_sql
  - execution_status
    值：bound/executed/failed/waiting_approval
  - execution_result_json
  - approval_status
  - create_user_id
  - create_user_name
  - created_at

  和现有表的关系

  保留现有：

  - src/xagent/web/models/vanna.py
  - src/xagent/web/models/vanna.py
  - src/xagent/web/models/vanna.py

  新增关系建议：

  - vanna_sql_assets.kb_id -> vanna_knowledge_bases.id
  - vanna_sql_assets.datasource_id -> text2sql_databases.id
  - vanna_sql_assets.origin_ask_run_id -> vanna_ask_runs.id
  - vanna_sql_assets.origin_training_entry_id -> vanna_training_entries.id
  - vanna_sql_asset_versions.asset_id -> vanna_sql_assets.id
  - vanna_sql_asset_runs.asset_id -> vanna_sql_assets.id

  语义上：

  - ask_run：候选 SQL 从哪来
  - training_entry：给检索增强什么知识
  - sql_asset：以后正式复用哪条 SQL

  API 设计

  建议新增 /api/vanna/assets

  1. 资产管理

  - POST /api/vanna/assets
    创建资产头
  - POST /api/vanna/assets/{asset_id}/versions
    新增版本
  - POST /api/vanna/assets/{asset_id}/publish
    发布版本
  - GET /api/vanna/assets
    列表
  - GET /api/vanna/assets/{asset_id}
    详情
  - GET /api/vanna/assets/{asset_id}/versions
    版本列表

  2. 资产命中与执行

  - POST /api/vanna/assets/resolve
    输入问题，返回命中的资产候选
  - POST /api/vanna/assets/{asset_id}/bind
    输入问题或显式参数，返回参数绑定结果
  - POST /api/vanna/assets/{asset_id}/execute
    绑定并执行
  - GET /api/vanna/assets/{asset_id}/runs
    执行记录

  3. ask 提升为资产

  - POST /api/vanna/ask-runs/{ask_run_id}/promote
    把某次 ask 的结果沉淀成 asset
  - POST /api/vanna/entries/{entry_id}/promote
    把某条训练 entry 提升成 asset

  参数 schema 规范

  建议 parameter_schema_json 长这样：

  [
    {
      "name": "start_date",
      "label": "开始日期",
      "data_type": "date",
      "required": true,
      "source_policy": "user_or_context",
      "default_value": null,
      "description": "统计开始日期，含当日",
      "validation": {
        "allow_relative_time": true
      }
    },
    {
      "name": "end_date",
      "label": "结束日期",
      "data_type": "date",
      "required": true,
      "source_policy": "derived",
      "default_value": null,
      "description": "统计结束日期，不含当日",
      "derive_from": {
        "kind": "exclusive_end_of_range",
        "ref": "start_date"
      }
    },
    {
      "name": "region_list",
      "label": "区域列表",
      "data_type": "string_array",
      "required": false,
      "source_policy": "user_or_default",
      "default_value": [],
      "description": "需要过滤的区域"
    }
  ]

  建议支持的数据类型先收敛到：

  - string
  - int
  - float
  - boolean
  - date
  - datetime
  - string_array
  - int_array

  模板 SQL 规范

  不要直接存执行态 SQL，存逻辑模板：

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

  但运行时不要直接字符串替换。要分两步：

  1. 逻辑模板渲染
  2. 驱动参数绑定编译

  最终执行前应得到：

  {
    "compiled_sql": "select dt, region, sum(amount) as revenue from dwd_order where dt >= :start_date and dt < :end_date
  and region in (:region_list_0, :region_list_1)",
    "bound_params": {
      "start_date": "2026-04-01",
      "end_date": "2026-04-08",
      "region_list_0": "east",
      "region_list_1": "north"
    }
  }

  LLM 职责

  在 asset-first 模式下，LLM 不该输出 SQL，而该输出绑定计划。

  建议输出格式：

  {
    "asset_code": "sales.daily_revenue_by_region",
    "confidence": 0.93,
    "bindings": {
      "start_date": "2026-04-01",
      "end_date": "2026-04-08",
      "region_list": ["east", "north"]
    },
    "missing_params": [],
    "assumptions": [
      "本周按自然周处理"
    ]
  }

  参数来源建议固化：

  - explicit_user
  - task_context
  - system_runtime
  - default_value
  - llm_inferred

  并记录到 binding_plan_json：

  {
    "start_date": {
      "value": "2026-04-01",
      "source": "llm_inferred"
    },
    "end_date": {
      "value": "2026-04-08",
      "source": "derived"
    }
  }

  运行时序

  1. asset-first

  - 用户提问
  - AssetResolver 按 asset_code/name/keywords/examples/vector 查候选
  - LLM 在候选中选一个资产并填参数
  - ParameterResolver 校验和补全
  - SqlTemplateCompiler 产出 compiled_sql + bound_params
  - 执行器执行
  - 写 vanna_sql_asset_runs

  2. ask-fallback

  - 资产未命中
  - 调用现有 src/xagent/core/vanna/ask_service.py
  - 生成 VannaAskRun
  - 用户确认“沉淀”
  - 生成 sql_asset + first_version
  - 可选同步生成 VannaTrainingEntry(question_sql)

  和现有 ask/train 的接口边界

  建议这样改，不要打破现有逻辑：

  - 保留 /api/vanna/ask
  - 保留 /api/vanna/train
  - 新增 /api/vanna/assets/...

  并新增一个编排入口：

  - POST /api/vanna/query

  语义：

  - 先 asset-first
  - 再 ask-fallback
  - 返回统一结构

  返回示例：

  {
    "mode": "asset_hit",
    "asset_id": 12,
    "asset_version_id": 34,
    "compiled_sql": "...",
    "bound_params": {},
    "execution_result": {}
  }

  或

  {
    "mode": "ask_generated",
    "ask_run_id": 88,
    "generated_sql": "...",
    "execution_result": {}
  }

  最小落地顺序

  1. 先建表

  - vanna_sql_assets
  - vanna_sql_asset_versions
  - vanna_sql_asset_runs

  2. 先做手工资产

  - 允许人工录入 SQL 模板和参数 schema
  - 先不做自动提升

  3. 再做资产检索

  - 先支持 asset_code/name/keywords
  - embedding 语义检索后加

  4. 再做参数装配

  - 先支持显式参数 + 简单时间推导
  - 再让 LLM 自动补参

  5. 最后做 ask 提升为资产

  - 从 ask_run 一键 promote

  一句话定性

  最终模型应该是：

  - ask 负责发现
  - train 负责记忆
  - asset 负责复用
  - binding 负责把资产变成一次真正可执行的 SQL
