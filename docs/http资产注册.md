# HTTP 资产注册设计说明

## 1. 背景与目标

当前仓库内已有一套 `datamake` 命名的 HTTP 资产实现，但本次需求不再迁移或复用这套宿主链路，而是单独建设一套新的 `gdp` HTTP 资产注册后端能力。

本次工作目标：

1. 新建 `gdp_http_resources` 表。
2. 新建对应 ORM 模型、migration、service、API。
3. 先只完成后端 CRUD，不改前端页面。
4. 删除采用软删除，保留 `status` 字段。
5. 新协议不再沿用当前 `xagent` 中偏执行导向的 `HttpEndpointSpec` 作为唯一协议，而是参考 `D:\code\http2mcp` 的定义方式，引入“模型可见层 + HTTP 执行层”的分层设计。

明确不做：

1. 不迁移现有 `datamake_http_resources` 数据。
2. 不保留 `/api/v1/datamake/http-assets` 兼容路由。
3. 不接 GDP 知识模型、知识投影、召回、MCP 运行时注册。
4. 不改现有前端页面和前端请求地址。

## 2. 设计来源：参考 http2mcp 的协议分层

参考项目：`D:\code\http2mcp`

`http2mcp` 中 HTTP 接口到 MCP Tool 的核心不是“一个 HTTP 配置对象”，而是两层协议叠加：

1. 模型 可见层
   - 定义工具名称、业务含义、输入参数结构、输出参数结构、行为注解。
2. HTTP 执行层
   - 定义真实请求如何发送、参数如何路由、响应如何组织。

其关键设计点包括：

1. `inputSchema` / `outputSchema` 用于表达模型侧的入参与出参契约。
2. `argsPosition` 用于表达参数从 MCP 入参到 HTTP path/query/header/body/cookie 的精确映射。
3. `requestTemplate` 用于表达请求模板和兜底组装策略。
4. `responseTemplate` / `errorResponseTemplate` 用于表达成功与失败响应如何组织成模型可读结果。
5. `annotations` 用于表达只读、破坏性、幂等性、开放世界等工具行为语义。

本次 `gdp` HTTP 资产协议将迁移这套设计思想，但当前阶段只做“注册与存储”，不做运行时 MCP Tool 动态注册。

## 3. 总体设计原则

### 3.1 不做三表，采用“一表三层”

虽然协议在领域上分三层：

1. 宿主管理层
2. MCP 可见层
3. HTTP 执行层

但当前 HTTP 资产仍然是一个整体编辑、整体保存、整体删除的聚合根。三层没有独立生命周期，因此数据库层先不拆成三张表，而采用：

1. 数据库一张主表：`gdp_http_resources`
2. 代码中明确分三层对象
3. API 请求与响应也明确按三层组织

这样可以同时获得：

1. CRUD 简单
2. 协议边界清晰
3. 后续如果确实出现独立生命周期，再拆表也有清晰路径

### 3.2 宿主管理字段拆列，协议字段按层分块存储

本次不采用单一 `tool_definition_json` 大字段包一切，也不采用所有字段完全平铺。

推荐方式：

1. 宿主管理字段拆列
2. MCP 可见层字段拆列或按块存储
3. HTTP 执行层字段拆列或按块存储

这样既能支持查询、治理和软删除，也能保留协议层次。

## 4. `gdp_http_resources` 表结构草案

### 4.1 宿主管理层字段

1. `id`
2. `resource_key`
   - 宿主资产稳定唯一标识，用于注册、跨表引用、导入幂等和后续外部系统对接
3. `system_short`
   - 系统简称，例如 `crm`、`erp`
4. `create_user_id`
   - 创建人
5. `create_user_name`
   - 创建人中文姓名
6. `visibility`
   - `private | shared | global`
7. `status`
   - 使用整数值节约存储：`0=draft`、`1=active`、`2=deleted`
8. `summary`
9. `tags_json`
10. `created_at`
11. `updated_at`

补充说明：

1. `resource_key` 不是展示字段，而是宿主侧“稳定资源编码”。
2. 它的作用是让资产在数据库 `id` 变化、跨环境迁移、外部引用或后续注册中心接入时，仍然有一个稳定标识。
3. `tool_name` 更偏 MCP/模型可见语义；`resource_key` 更偏宿主治理与系统集成语义。
4. 如果当前阶段确认不会出现外部引用、导入幂等、运行时注册等场景，也可以后续评估是否弱化或收敛这个字段，但在现阶段保留更稳妥。

### 4.2 MCP 可见层字段

1. `tool_name`
2. `tool_description`
3. `input_schema_json`
4. `output_schema_json`
5. `annotations_json`

说明：

1. `tool_name` 与 `resource_key` 不强制视为同一个概念。
2. `tool_name` 表达 MCP Tool 标识。
3. `resource_key` 表达宿主资产标识。
4. 短期可保持相同值，但模型语义上不绑定。

### 4.3 HTTP 执行层字段

1. `method`
   - 当前先支持 `GET | POST`
2. `url_mode`
   - `direct | tag`
3. `direct_url`
4. `sys_label`
   - URL 标签或宿主地址簇标识，仅在 `url_mode=tag` 时使用
5. `url_suffix`
6. `args_position_json`
7. `request_template_json`
8. `response_template_json`
9. `error_response_template`
10. `auth_json`
11. `headers_json`
12. `timeout_seconds`

说明：

1. `input_schema_json` 与 `args_position_json` 必须分开存储。
2. `output_schema_json` 与 `response_template_json` 必须分开存储。
3. `request_template_json` 不替代 `args_position_json`，它只是高级模板层。

### 4.4 约束与索引建议

建议约束：

1. `resource_key` 唯一。
2. `tool_name` 可选唯一。
   - 若后续希望 MCP Tool 名全局唯一，则加唯一约束。
3. `status` 建议使用 `SMALLINT` 存储。

建议索引：

1. `create_user_id`
2. `status`
3. `visibility`
4. `system_short`

## 5. API 设计

本次只提供新的 `gdp` 路由，不提供 `datamake` 兼容入口。

建议路由前缀：

`/api/v1/gdp/http-assets`

### 5.1 请求体结构

统一按三层结构提交：

```json
{
  "resource": {
    "resource_key": "crm_create_signup",
    "system_short": "crm",
    "visibility": "private",
    "summary": "营销报名创建接口",
    "tags_json": ["crm", "signup"]
  },
  "tool_contract": {
    "tool_name": "create_signup",
    "tool_description": "向营销系统创建报名记录，并返回 signup_id",
    "input_schema_json": {},
    "output_schema_json": {},
    "annotations_json": {
      "title": "创建报名记录",
      "readOnlyHint": false,
      "destructiveHint": false,
      "idempotentHint": true,
      "openWorldHint": false
    }
  },
  "execution_profile": {
    "method": "POST",
    "url_mode": "direct",
    "direct_url": "https://api.example.com/signup",
    "sys_label": null,
    "url_suffix": null,
    "args_position_json": {},
    "request_template_json": {},
    "response_template_json": {},
    "error_response_template": "接口失败：HTTP {{ status_code }}",
    "auth_json": {},
    "headers_json": {},
    "timeout_seconds": 30
  }
}
```

### 5.2 CRUD 接口

1. `GET /api/v1/gdp/http-assets`
   - 返回列表
   - 默认过滤 `status=2`

2. `GET /api/v1/gdp/http-assets/{id}`
   - 返回完整详情

3. `POST /api/v1/gdp/http-assets`
   - 创建资产
   - 服务端填充 `create_user_id`、`create_user_name`、`status`

4. `PUT /api/v1/gdp/http-assets/{id}`
   - 全量更新
   - 当前阶段按整包更新，不做 patch 语义

5. `DELETE /api/v1/gdp/http-assets/{id}`
   - 软删除
   - 仅将 `status` 置为 `2`

### 5.3 返回结构

统一响应格式：

```json
{
  "data": {}
}
```

列表接口返回轻量字段：

1. `id`
2. `resource_key`
3. `status`
4. `system_short`
5. `visibility`
6. `tool_name`
7. `tool_description`
8. `method`
9. `url_mode`
10. `direct_url`
11. `sys_label`
12. `url_suffix`
13. `updated_at`

详情接口返回完整三层结构。

## 6. 状态语义

当前阶段状态采用最小集合：

1. `0 = draft`
2. `1 = active`
3. `2 = deleted`

约束：

1. `POST` 默认写入 `1`
2. `GET list` 默认不返回 `2`
3. `DELETE` 不物理删除，只改 `status=2`
4. 当前阶段不支持恢复接口
5. 当前阶段不允许更新 `status=2` 记录

## 7. 校验设计

### 7.1 校验层次

建议拆成两层：

1. Pydantic 模型负责结构合法
2. 独立 validator 负责跨层与跨字段语义校验

建议新增：

1. `src/xagent/core/gdp/http_asset_protocol.py`
   - 定义三层协议模型
2. `src/xagent/core/gdp/http_asset_validator.py`
   - 定义一致性校验规则

### 7.2 基础字段校验

1. `resource.resource_key` 必填
2. `resource.system_short` 必填
3. `tool_contract.tool_name` 必填
4. `tool_contract.tool_description` 必填
5. `execution_profile.method` 仅允许 `GET | POST`
6. `execution_profile.url_mode` 仅允许 `direct | tag`
7. `url_mode=direct` 时 `direct_url` 必填
8. `url_mode=tag` 时 `sys_label` 必填
9. 前端或调用方不能直接把 `status` 写成 `2`

### 7.3 MCP 可见层校验

1. `input_schema_json.type` 顶层必须为 `object`
2. `input_schema_json.properties` 必须是对象
3. `input_schema_json.required` 若存在必须为字符串数组
4. `output_schema_json` 非空时必须是合法 JSON Schema 对象
5. `annotations_json` 仅允许以下字段：
   - `title`
   - `readOnlyHint`
   - `destructiveHint`
   - `idempotentHint`
   - `openWorldHint`

关键约束：

禁止把内部路由信息偷偷塞到 `input_schema_json` 里，例如：

1. `x-args-route`
2. `x-location`

路由必须全部放在 `args_position_json` 中。

### 7.4 HTTP 执行层校验

以下规则参考 `http2mcp` 迁移：

1. `args_position_json` 的 source path 不能为空
2. source path 必须存在于 `input_schema_json`
3. 不允许父子路径同时路由
   - 例如 `user` 与 `user.id`
4. `arrayStyle` 仅允许 query，且 source 字段类型必须是 array
5. `objectStyle` 仅允许 query，且 source 字段类型必须是 object
6. `path` 映射不能接 object/array
7. URL 有占位符时，必须存在对应 path 路由
8. URL 无占位符时，不能配置 path 路由
9. `GET` 禁止 body 路由
10. `GET` 禁止 `request_template_json.body`
11. `GET` 禁止 `argsToJsonBody=true`
12. `request_template_json.body` 与 body 路由互斥
13. `request_template_json.body / argsToJsonBody / argsToUrlParam` 三选一
14. `response_template_json.body` 与 `prependBody/appendBody` 互斥
15. `response_template_json.extractionRules` 若存在，必须为对象数组，且每项都需要 `key/path`
16. `response_template_json.successRule` 若存在，必须包含 `path`

## 8. 实施顺序

建议按以下顺序落地：

1. 新增 `gdp_http_resources` migration
2. 新增 ORM 模型 `GdpHttpResource`
3. 在 `web.models.__init__` 与 `database.init_db()` 中注册新模型
4. 新增 `core/gdp/http_asset_protocol.py`
5. 新增 `core/gdp/http_asset_validator.py`
6. 新增 `core/gdp/application/http_resource_service.py`
7. 新增 `web/api/gdp_http_assets.py`
8. 在 `web/app.py` 中挂载新的 router
9. 为 CRUD 与校验补充测试

## 9. 当前结论

本次 `gdp` HTTP 资产注册设计不应再简单复制现有 `datamake` 的 `tool_definition_json` 做法，而应参考 `http2mcp` 的协议边界，形成如下结构：

1. 数据库一张主表
2. 领域模型三层分离
3. API 请求与响应按三层组织
4. 校验规则迁移 `http2mcp` 的核心约束

这样既能满足当前“先把 HTTP 资产注册 CRUD 做好”的目标，也能为后续前端切换与 MCP/知识层对接留出清晰扩展路径。
