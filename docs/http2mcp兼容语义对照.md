# http2mcp 页面语义与 Xagent 当前实现对照

## 1. 目标

本文档只回答一件事：

原 `http2mcp` 页面在 `ProtocolConfig.vue` / `ToolDetail.vue` 上允许用户配置的 HTTP 转换语义，当前 `dev0403` 分支里的 Xagent 已经如何承接，哪些地方是等价实现，哪些地方仍然是约束性兼容。

当前落地形态不是“每个 HTTP 资产直接暴露成一个 MCP tool”，而是两个固定 runtime tool：

1. `query_http_resource`
2. `execute_http_resource`

## 2. 模型侧暴露形态变化

### 原 http2mcp

- 模型看到的是单个接口最终展开后的 MCP tool schema
- tool 的入参 schema 就是页面上配置好的 `tool_contract.input_schema_json`
- 真实 HTTP 投递位置、模板和响应处理都藏在执行层，不直接暴露给模型

### 当前 Xagent

- 模型先看到两个固定 tool，而不是每个 HTTP 资产一个 tool
- `query_http_resource` 返回候选资产列表，每个候选项里保留完整 `tool_contract`
- `execute_http_resource` 接收选中的 `resource_key/resource_id + arguments`

结论：

- 模型可见层保留了原 MCP tool schema 语义
- 变化的是暴露方式，从“静态全量 tool 暴露”改成“先查候选，再执行”

## 3. query_http_resource 暴露给模型的内容

`query_http_resource` 返回的核心结构位于：

- `src/xagent/core/gdp/application/http_runtime_models.py`

单个候选项包含：

1. `resource_id`
2. `resource_key`
3. `system_short`
4. `summary`
5. `tags_json`
6. `visibility`
7. `tool_contract`
8. `required_argument_names`
9. `argument_outline`
10. `match_context`

其中 `tool_contract` 仍然是原 MCP 可见层：

1. `tool_name`
2. `tool_description`
3. `input_schema_json`
4. `output_schema_json`
5. `annotations_json`

补充出的两层是：

1. `required_argument_names`
   用于模型快速判断顶层缺参
2. `argument_outline`
   用于模型快速理解嵌套参数，不必首轮深读整份 schema

## 4. 页面配置项到运行时的映射

### 4.1 `tool_contract.input_schema_json`

页面语义：

- 声明模型可见入参
- 可以是扁平字段
- 也可以是完整 JSON Schema

当前实现：

- `query_http_resource` 原样返回
- `execute_http_resource` 按这份 schema 做调用期参数校验

兼容结论：

- 兼容扁平 schema
- 兼容 object / array 嵌套 schema
- 调用期缺参提示会返回 `missing_required_paths`

### 4.2 `argsPosition`

页面语义：

- source path 支持 `a.b[0].c`
- 每个 source path 投递到 HTTP 请求某个位置
- 支持 `path/query/header/body/cookie`

当前实现：

- `HttpRequestAssembler` 负责按 source path 从 `arguments` 取值
- `HttpAssetValidator` 负责注册期静态校验

兼容结论：

- 已支持 `path/query/header/body/cookie`
- 已支持数组路径和深层对象路径
- 已支持 query 的 `arrayStyle` / `objectStyle`

### 4.3 扁平参数声明 + 真实投递位置映射

页面语义：

- tool 声明参数可以是扁平的
- 执行时再通过 `argsPosition` 决定真实投递位置

当前实现：

- `arguments` 一直按 `input_schema_json` 的结构传入
- `execute_http_resource` 再通过 `args_position_json` 把参数投到 URL/query/header/body/cookie

兼容结论：

- 该语义保持不变
- 模型只管按 schema 传 `arguments`
- HTTP 细节仍由执行层接管

### 4.4 `requestTemplate.url`

页面语义：

- 可以覆盖最终请求 URL
- 支持模板表达式

当前实现：

- 已支持
- 模板上下文支持 `args` / `arguments` / `endpoint` / `headers` / `context`

### 4.5 `requestTemplate.method`

页面语义：

- 可在模板层覆盖方法

当前实现：

- 已支持字符串覆盖
- 最终 method 会影响 GET/body 约束与返回快照

### 4.6 `requestTemplate.headers`

页面语义：

- 支持模板化 header
- 页面通常以 `{key, value}` 列表形式配置

当前实现：

- 已支持 list 和 dict 两种写法
- 每个 key/value 都走 Jinja 渲染

### 4.7 `requestTemplate.body`

页面语义：

- 支持模板渲染 body
- 原始设计本质上是“模板生成最终请求体”

当前实现：

- 已支持 Jinja 渲染
- 若渲染结果能解析为 JSON，则写入 `json_body`
- 若不能解析为 JSON，则保留为 `text_body`

兼容结论：

- 对 JSON body 场景兼容
- 对纯文本 body 场景也已兼容

### 4.8 `argsToUrlParam`

页面语义：

- 将未被显式路由消费的顶层参数自动并入 URL query

当前实现：

- 已按“仅 unmatched top-level args”处理
- 不会重复投递已被 `argsPosition` 消费的顶层 root

### 4.9 `argsToJsonBody`

页面语义：

- 将未被显式路由消费的顶层参数并入 JSON body
- 显式 body route 需要保留

当前实现：

- 已支持“显式 body route + unmatched args”合并
- 不再覆盖显式 body route

### 4.10 `responseTemplate.body`

页面语义：

- 完全覆盖模型看到的响应文本

当前实现：

- 已支持
- 模板上下文中可使用 `resp_json` / `resp_text` / `extracted` / `status_code`

### 4.11 `responseTemplate.prependBody` / `appendBody`

页面语义：

- 在默认响应文本前后追加模板内容

当前实现：

- 已支持
- 与 `responseTemplate.body` 保持互斥校验

### 4.12 `errorResponseTemplate`

页面语义：

- 为失败场景提供单独模板

当前实现：

- 已接入失败渲染链
- 返回仍统一包裹在 `error.message` / `error.details`

## 5. 模板能力兼容情况

原 `http2mcp` 偏 Jinja 语义。

当前实现已支持：

1. `tojson`
2. `fromjson`
3. `urlencode`
4. `b64encode`
5. `dig`

并且专门处理了这类场景：

- `args.items`
- `args.values`
- `args.keys`

避免字典方法名覆盖真实 JSON key。

## 6. 当前 validator 承接的页面规则

当前注册期校验已覆盖：

1. 顶层 `input_schema_json.type` 必须为 `object`
2. 不允许 schema 内部出现保留扩展字段
3. source path 必须能在 schema 中解析
4. 不允许父子路径同时路由
5. `path` 不能映射 object/array
6. `arrayStyle` 仅允许 query 且源字段必须是 array
7. `objectStyle` 仅允许 query 且源字段必须是 object
8. GET 禁止 body route
9. GET 禁止 `request_template_json.body`
10. GET 禁止 `argsToJsonBody`
11. `request_template_json.body` 与 body route 互斥
12. `body / argsToJsonBody / argsToUrlParam` 三选一
13. `responseTemplate.body` 与 `prependBody/appendBody` 互斥
14. URL path placeholder 与 path route 双向对齐
15. 重复目标投递会被拒绝
16. `request_template_json.method` 只允许 `GET/POST`
17. `request_template_json.headers` 必须为对象或 `{key,value}` 数组
18. `request_template_json.body/url` 必须为字符串
19. `response_template_json.body/prependBody/appendBody` 必须为字符串

## 7. execute_http_resource 的复杂映射链路

当前执行链路是：

1. 通过 `resource_key/resource_id` 取出资产
2. 还原 `HttpRuntimeDefinition`
3. 按 `input_schema_json` 做调用期校验
4. `HttpRequestAssembler` 处理：
   - deep source path 取值
   - `path/query/header/body/cookie` 落点
   - `argsToUrlParam`
   - `argsToJsonBody`
   - `requestTemplate.url/method/headers/body`
5. `HttpInvoker` 处理：
   - headers
   - cookies 合并到 `Cookie`
   - auth
   - timeout
6. `HttpResponseInterpreter` 处理：
   - 响应压缩
   - `extractionRules`
   - `successRule`
   - `responseTemplate.body/prependBody/appendBody`
   - `errorResponseTemplate`

## 8. 当前已验证的兼容测试

当前测试已覆盖：

1. `argsToUrlParam` 只合并未匹配顶层参数
2. `argsToJsonBody` 保留显式 body route
3. template headers + cookies + body + query style
4. 响应数组路径提取
5. `responseTemplate.body`
6. `prependBody/appendBody`
7. GET + body 拦截
8. validator 接受 array source path + cookie route
9. tool 注册与 dry-run 可调用

## 9. 仍需明确的非完全等价点

以下点当前是“高兼容”，但不等于已经完全复制原实现：

1. 页面层可视化编辑细节
   当前 Xagent 承接的是协议语义，不是前端编辑体验
2. 更细粒度的前端提示文案
   当前后端已覆盖主要规则，但未完全复刻原前端所有交互态提示文本

## 10. ProtocolConfig / ToolDetail 逐项矩阵

| 原页面配置项 | 原页面语义 | 当前 Xagent 对应字段/实现 | 当前状态 |
|---|---|---|---|
| `Tool 名称` | MCP tool name | `tool_contract.tool_name` | 已兼容 |
| `Tool 描述` | MCP tool description | `tool_contract.tool_description` | 已兼容 |
| `Tool 入参 visual/json` | 可视化树或原始 JSON Schema | `tool_contract.input_schema_json` | 已兼容 |
| `Tool 出参 visual/json` | output schema | `tool_contract.output_schema_json` | 已兼容 |
| `Annotations.title` | 人类可读标题 | `annotations_json.title` | 已兼容 |
| `readOnlyHint` | 只读提示 | `annotations_json.readOnlyHint` | 已兼容 |
| `destructiveHint` | 破坏性提示 | `annotations_json.destructiveHint` | 已兼容 |
| `idempotentHint` | 幂等提示 | `annotations_json.idempotentHint` | 已兼容 |
| `openWorldHint` | 外部交互提示 | `annotations_json.openWorldHint` | 已兼容 |
| `请求方法` | 只允许 `GET/POST` | `execution_profile.method` | 已兼容 |
| `urlMode=direct/tag` | 直连或系统标签解析 | `execution_profile.url_mode` | 已兼容 |
| `direct_url` | 直接请求 URL | `execution_profile.direct_url` | 已兼容 |
| `sysLabel + urlSuffix` | tag 模式下拼 base_url + suffix | `execution_profile.sys_label/url_suffix` | 已兼容 |
| `argsPosition` | source path 到 path/query/header/body/cookie 的映射 | `execution_profile.args_position_json` | 已兼容 |
| `argsPosition.arrayStyle` | query 数组投递策略 | validator + assembler | 已兼容 |
| `argsPosition.objectStyle` | query 对象投递策略 | validator + assembler | 已兼容 |
| `argsPosition path 占位符校验` | path 目标必须与 URL 占位符一一对应 | validator | 已兼容 |
| `reqBodyStrategy=none` | 未匹配参数自动并入 URL query | `request_template_json.argsToUrlParam` | 已兼容 |
| `reqBodyStrategy=json` | 未匹配参数自动生成 JSON body | `request_template_json.argsToJsonBody` | 已兼容 |
| `reqBodyStrategy=custom` | 使用自定义 body 模板 | `request_template_json.body` | 已兼容 |
| `requestTemplate.url` | 模板覆盖 URL | `request_template_json.url` | 已兼容 |
| `requestTemplate.method` | 模板覆盖 method | `request_template_json.method` | 已兼容 |
| `requestTemplate.headers` | 模板化 headers | `request_template_json.headers` | 已兼容 |
| `responseTemplate.body` | 覆盖成功响应文本 | `response_template_json.body` | 已兼容 |
| `responseTemplate.prependBody` | 成功响应前缀 | `response_template_json.prependBody` | 已兼容 |
| `responseTemplate.appendBody` | 成功响应后缀 | `response_template_json.appendBody` | 已兼容 |
| `errorResponseTemplate` | 非 2xx / 错误兜底模板 | `error_response_template` | 已兼容 |
| `预览 Schema / 报文` | 预览最终 schema 与请求报文 | `POST /api/v1/gdp/http-assets/assemble`，复用 runtime assembler | 已兼容 |

## 11. 当前结论

如果以“页面配置表达的 HTTP 协议转换语义”为准，而不是以“每个接口最终暴露成 MCP tool 的形态”为准，那么当前 `dev0403` 分支已经完成了大部分关键兼容：

1. 模型可见层 schema 语义保留
2. 参数路由语义保留
3. 模板渲染语义大体保留
4. 响应解释语义保留
5. 执行结果和错误恢复语义比原实现更结构化

最大的架构变化只有一个：

- 原来是“HTTP 资产直接展开成 MCP tool”
- 现在是“先 `query_http_resource`，再 `execute_http_resource`”

这个变化影响的是模型如何发现接口，不影响页面上原有协议配置字段大部分语义。
