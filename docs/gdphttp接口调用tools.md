# GDP HTTP 接口调用 Tools 设计说明

## 1. 文档目标

本文档用于在现有 `gdp_http_resources` 注册协议之上，补齐“模型如何查找 HTTP 资产、理解接口参数、执行接口调用并拿到响应结果”的运行时设计。

本文档聚焦两个工具：

1. `query_http_resource`
2. `execute_http_resource`

这两个工具共同承担 GDP HTTP 资产从“可注册”走向“可被模型真实使用”的完整链路。

---

## 2. 背景与问题定义

当前系统已经完成以下能力：

1. `gdp_http_resources` 表与 ORM 模型落库
2. HTTP 资产 CRUD
3. “模型可见层 + HTTP 执行层”协议分层
4. 资产注册期的结构校验

当前系统尚未打通以下能力：

1. 模型根据用户目标查找最合适的 HTTP 资产
2. 模型理解接口需要哪些参数
3. 参数按协议转换成真实 HTTP 请求
4. 发起 HTTP 请求
5. 把响应转换成模型可继续消费的结果

换句话说，当前 `gdp_http_resource` 还停留在“资产注册后台”，尚未形成“模型运行时工具”。

---

## 3. 设计结论

### 3.1 不采用“每个 HTTP 资产直接注册成独立工具”的方式

虽然参考项目 `http2mcp` 最终会把每个接口注册成独立 MCP Tool，但当前 Xagent 阶段更适合采用“双工具模式”：

1. `query_http_resource`
   - 面向模型的工具发现器
   - 返回候选 HTTP 资产的模型可见层定义
2. `execute_http_resource`
   - 面向运行时的执行器
   - 接收已选中的 HTTP 资产和参数，完成协议转换、发送请求、返回结果

### 3.2 采用“双阶段调用链”

完整运行链路如下：

1. 用户提出业务目标
2. 模型调用 `query_http_resource`
3. 系统返回候选 HTTP 资产及完整 MCP 可见层字段
4. 模型选择某个候选资产
5. 若参数不足，模型继续追问用户
6. 参数齐备后，模型调用 `execute_http_resource`
7. 系统完成协议转换、HTTP 调用、结果格式化
8. 模型根据返回结果组织最终回答

---

## 4. 为什么采用双工具模式

### 4.1 当前阶段工具总量和资产总量不适合一次性全暴露

如果每条 HTTP 资产都直接暴露为模型工具，会带来以下问题：

1. 工具列表过长，上下文噪声高
2. 模型难以稳定选中正确工具
3. 资产注册和工具暴露耦合过重
4. 后续权限、可见性、状态过滤会变复杂

### 4.2 双工具模式更适合当前 GDP HTTP 资产形态

当前 `gdp_http_resources` 已经是“资产注册表”，不是 MCP 运行时注册中心。  
因此当前阶段最合理的做法是：

1. 先把资产查找做成工具
2. 再把资产执行做成工具

这样既保留了 `http2mcp` 的协议转换思想，又避免过早引入动态工具注册复杂度。

### 4.3 双工具模式更符合模型决策过程

模型在真实任务里，往往先要解决：

1. 我应该用哪个接口
2. 这个接口缺什么参数
3. 参数齐了以后怎么调用

双工具模式正好对应这三个思维步骤。

---

## 5. 与 http2mcp 的关系

### 5.1 需要借鉴的不是“形态”，而是“职责拆分”

参考 `http2mcp`，真正值得借鉴的是以下运行时职责：

1. 参数校验与类型转换
2. `argsPosition` 路由
3. `requestTemplate` 模板渲染
4. 鉴权注入与 HTTP 调用
5. `responseTemplate` / `errorResponseTemplate` 响应格式化

### 5.2 在 GDP 里对应的映射关系

| http2mcp 能力 | GDP 建议承载方式 |
|---|---|
| 工具搜索 / 延迟发现 | `query_http_resource` |
| 工具调用 | `execute_http_resource` |
| 参数路由引擎 | GDP 内部 `HttpArgumentRouter` |
| 模板渲染引擎 | GDP 内部 `HttpTemplateRenderer` |
| HTTP 请求客户端 | GDP 内部 `HttpInvoker` |
| 响应折叠与格式化 | GDP 内部 `HttpResponseInterpreter` |

结论：

GDP 不直接复制 `http2mcp` 的“每个接口直接注册为 MCP Tool”，而是复制其“协议转换调用”的分层思路。

---

## 6. 现有 GDP HTTP 资产协议的角色定位

当前协议字段仍然维持三层：

### 6.1 宿主管理层

核心字段：

1. `resource_key`
2. `system_short`
3. `visibility`
4. `status`
5. `summary`
6. `tags_json`

职责：

- 资产身份
- 权限与可见性
- 治理状态
- 检索召回辅助文本

### 6.2 模型可见层

核心字段：

1. `tool_name`
2. `tool_description`
3. `input_schema_json`
4. `output_schema_json`
5. `annotations_json`

职责：

- 让模型理解接口能做什么
- 让模型理解接口需要什么参数
- 让模型理解接口大致返回什么结果

### 6.3 HTTP 执行层

核心字段：

1. `method`
2. `url_mode`
3. `direct_url`
4. `sys_label`
5. `url_suffix`
6. `args_position_json`
7. `request_template_json`
8. `response_template_json`
9. `error_response_template`
10. `auth_json`
11. `headers_json`
12. `timeout_seconds`

职责：

- 让运行时知道如何把“业务参数”变成“真实 HTTP 请求”
- 让运行时知道如何把“真实 HTTP 响应”变成“模型可读结果”

---

## 7. Tool 一：`query_http_resource`

### 7.1 工具目标

`query_http_resource` 用于帮助模型从 GDP HTTP 资产库中查找与当前任务最相关的候选接口，并直接返回模型可见层完整定义。

在完整定义之外，建议同时返回一层“参数摘要”，用于降低模型首轮理解成本。这样模型不需要一上来就完整展开
`input_schema_json`，也能快速判断：

1. 当前接口顶层必填参数有哪些
2. 是否还需要继续向用户追问补参
3. 复杂对象参数里有哪些关键嵌套字段

它本质上是：

1. 资产检索器
2. 轻量工具发现器
3. 模型决策前的上下文压缩器

### 7.2 工具职责

它负责：

1. 根据用户任务检索候选 HTTP 资产
2. 过滤不可见、已删除、不可用资产
3. 对候选结果排序
4. 返回候选资产的完整 MCP 可见层字段
5. 返回模型易消费的参数摘要层

它不负责：

1. 发起 HTTP 请求
2. 执行参数校验
3. 暴露执行层内部细节

### 7.3 输入协议建议

```json
{
  "query": "按手机号查询 CRM 报名记录",
  "system_short": "crm",
  "top_k": 5
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `query` | 是 | 用户当前的自然语言任务 |
| `system_short` | 否 | 指定系统范围，缩小搜索空间 |
| `top_k` | 否 | 返回候选数，默认 5 |

### 7.4 检索字段建议

建议检索以下字段：

1. `tool_name`
2. `tool_description`
3. `summary`
4. `resource_key`
5. `system_short`
6. `tags_json`
7. `input_schema_json` 中参数名与字段说明
8. `output_schema_json` 中字段说明
9. `annotations_json.title`

### 7.5 排序建议

建议采用规则加权排序：

1. `system_short` 精确匹配优先
2. `tool_description` 和 `summary` 命中优先
3. `input_schema_json` 中参数语义命中加分
4. 查询类意图优先匹配 `readOnlyHint=true`
5. 写入类意图优先匹配非只读接口

### 7.6 返回协议建议

单条候选建议返回：

```json
{
  "resource_id": 12,
  "resource_key": "crm_query_signup",
  "system_short": "crm",
  "summary": "根据手机号或报名单号查询报名记录",
  "tags_json": ["crm", "signup", "query"],
  "visibility": "shared",
  "required_argument_names": ["mobile", "payload"],
  "argument_outline": [
    {
      "name": "mobile",
      "path": "mobile",
      "type": "string",
      "description": "手机号",
      "required": true
    },
    {
      "name": "payload",
      "path": "payload",
      "type": "object",
      "description": "扩展查询条件",
      "required": true
    },
    {
      "name": "channel",
      "path": "payload.channel",
      "type": "string",
      "description": "渠道编码",
      "required": true
    }
  ],
  "tool_contract": {
    "tool_name": "query_signup_record",
    "tool_description": "根据手机号或报名单号查询报名记录，返回报名状态、报名时间和业务结果",
    "input_schema_json": {},
    "output_schema_json": {},
    "annotations_json": {}
  },
  "match_context": {
    "score": 0.91,
    "matched_fields": [
      "tool_description",
      "input_schema_json.properties.mobile.description"
    ],
    "intent_hint": "query"
  }
}
```

### 7.7 必须返回的模型可见层字段

这里明确要求完整返回以下字段：

1. `tool_name`
2. `tool_description`
3. `input_schema_json`
4. `output_schema_json`
5. `annotations_json`
6. `required_argument_names`
7. `argument_outline`

原因：

1. 模型需要根据 `tool_description` 判断接口职责
2. 模型需要根据 `input_schema_json` 判断缺少哪些参数
3. 模型需要根据 `output_schema_json` 预期响应结构
4. 模型需要根据 `annotations_json` 理解接口是否只读、是否可能写入
5. 模型需要根据 `required_argument_names` 先判断顶层关键参数是否缺失
6. 模型需要根据 `argument_outline` 快速组织追问话术，而不是每次完整深读 schema

### 7.8 不建议返回的字段

不建议在 `query_http_resource` 中返回以下字段给模型：

1. `auth_json`
2. `headers_json`
3. `request_template_json`
4. `response_template_json`
5. `error_response_template`
6. `args_position_json`
7. `timeout_seconds`

原因：

- 这些属于执行层内部协议
- 模型知道这些细节没有直接收益
- 容易让模型误把执行策略当成决策输入

---

## 8. Tool 二：`execute_http_resource`

### 8.1 工具目标

`execute_http_resource` 用于接收模型已经选定的 HTTP 资产和参数，完成协议转换、真实 HTTP 调用、响应格式化，并把结果返回给模型。

### 8.2 工具职责

它负责：

1. 根据 `resource_key` 或 `resource_id` 读取资产
2. 校验调用权限和资产状态
3. 校验本次参数是否满足 `input_schema_json`
4. 按 `args_position_json` 路由参数
5. 按 `request_template_json` 渲染请求
6. 解析真实 URL
7. 注入鉴权、请求头和超时
8. 发起 HTTP 调用
9. 使用 `response_template_json` / `error_response_template` 格式化结果

它不负责：

1. 搜索接口
2. 帮模型选择接口
3. 从自然语言中猜接口

### 8.3 输入协议建议

```json
{
  "resource_key": "crm_query_signup",
  "arguments": {
    "mobile": "13800138000"
  },
  "dry_run": false
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `resource_key` | 是 | 已选中的 HTTP 资产稳定标识 |
| `arguments` | 是 | 传给接口的业务参数 |
| `dry_run` | 否 | 若为 true，只返回组装结果，不发请求 |

### 8.4 输出协议建议

```json
{
  "resource": {
    "resource_key": "crm_query_signup",
    "tool_name": "query_signup_record"
  },
  "request": {
    "method": "GET",
    "url": "https://api.example.com/signup?mobile=13800138000",
    "headers": {
      "Accept": "application/json"
    }
  },
  "response": {
    "status_code": 200,
    "ok": true,
    "content_type": "application/json",
    "body": {},
    "rendered_text": "报名记录查询成功，当前状态为已提交。"
  },
  "error": null
}
```

说明：

1. `request.headers` 应脱敏，不能返回明文 token
2. `response.body` 应做长度控制，避免过大响应直接污染上下文
3. `rendered_text` 是给模型阅读的主结果
4. `body` 是结构化补充结果

当本次调用因为缺参或参数格式错误失败时，建议 `error.type=parameter_error`
额外返回结构化补参信息，而不只是自然语言报错。例如：

```json
{
  "error": {
    "type": "parameter_error",
    "message": "arguments.mobile 为必填参数",
    "details": {
      "errors": ["arguments.mobile 为必填参数"],
      "missing_required_paths": ["mobile"],
      "required_argument_names": ["mobile", "payload"],
      "argument_outline": [
        {
          "name": "mobile",
          "path": "mobile",
          "type": "string",
          "description": "手机号",
          "required": true
        }
      ]
    }
  }
}
```

这样模型可以直接基于 `missing_required_paths` 决定补问哪些字段，
再结合 `argument_outline` 组织追问内容，而不需要重新读完整 schema 才能恢复执行。

进一步建议所有错误都补一个统一的 `details.resolution`，把运行时建议的下一步动作显式返回，例如：

```json
{
  "resolution": {
    "suggested_next_action": "ask_user_for_missing_arguments",
    "can_retry": true,
    "needs_user_input": true
  }
}
```

建议动作语义可以先收敛为以下几类：

1. `query_http_resource`
   资源不存在、不可见，建议模型重新检索候选接口
2. `ask_user_for_missing_arguments`
   缺少必填参数，建议模型向用户补问
3. `correct_arguments_and_retry`
   参数类型或格式不对，但不一定缺字段，建议模型修正后重试
4. `check_runtime_configuration`
   运行时配置缺失，例如 `tag` 模式没有找到 base_url
5. `retry_execute_http_resource`
   偏瞬时性的网络或超时问题，可以考虑直接重试
6. `inspect_call_configuration`
   更像资产配置问题，需要检查调用定义
7. `explain_business_failure`
   HTTP 调用成功但业务判定失败，建议直接把失败语义告诉用户

---

## 9. execute 工具的内部运行时分层

### 9.1 推荐拆成六层

建议内部执行链拆成以下六层：

1. `HttpResourceResolver`
2. `HttpRuntimeDefinitionAssembler`
3. `HttpArgumentValidator`
4. `HttpRequestAssembler`
5. `HttpInvoker`
6. `HttpResponseInterpreter`

### 9.2 `HttpResourceResolver`

职责：

1. 根据 `resource_key` 或 `resource_id` 查资源
2. 校验 `status=ACTIVE`
3. 校验当前用户是否有可见权限

输出：

- `GdpHttpResource`

### 9.3 `HttpRuntimeDefinitionAssembler`

职责：

1. 把 ORM 模型恢复成运行时定义对象
2. 把数据库存储字段收敛成执行时稳定结构

建议输出对象至少包含：

1. 模型可见层字段
2. 执行层字段
3. 运行时需要的默认值和规整化数据

### 9.4 `HttpArgumentValidator`

职责：

1. 按 `input_schema_json` 做调用期参数校验
2. 处理必填、类型、枚举、正则、最值约束
3. 支持 object / array 类型解析

关键原则：

- 注册期校验和调用期校验必须分开
- 注册期检查“资产定义是否合法”
- 调用期检查“本次调用参数是否合法”

### 9.5 `HttpRequestAssembler`

职责：

1. 按 `args_position_json` 路由参数
2. 按 `request_template_json` 进行模板渲染
3. 最终组装成真实 HTTP 请求

建议拆成两个内部步骤：

1. 参数路由
2. 模板覆盖

这样错误定位更清晰。

### 9.6 `HttpInvoker`

职责：

1. 解析最终 URL
2. 注入鉴权
3. 注入 headers
4. 注入 timeout
5. 发起真实 HTTP 请求
6. 捕获网络异常、超时异常、状态码异常

### 9.7 `HttpResponseInterpreter`

职责：

1. 解析响应状态
2. 处理 JSON / 文本响应
3. 应用 `response_template_json`
4. 应用 `error_response_template`
5. 生成给模型阅读的 `rendered_text`
6. 生成结构化 `body`

---

## 10. 参数路由与模板渲染建议

### 10.1 参数路由职责

参数路由只负责：

1. 读取 `arguments`
2. 按 `source_path` 提取值
3. 按 `in=path/query/header/body` 写入不同区域
4. 处理 `arrayStyle` 和 `objectStyle`

它不负责：

1. 模板字符串替换
2. 发 HTTP 请求
3. 响应格式化

### 10.2 模板渲染职责

模板渲染只负责：

1. 渲染 URL 模板
2. 渲染 Header 模板
3. 渲染 Body 模板
4. 渲染成功响应模板
5. 渲染失败响应模板

关键约束：

1. `request_template_json.body` 与 body 路由互斥
2. `argsToJsonBody` / `argsToUrlParam` / 显式 `body` 三选一
3. `GET` 请求禁止 body

这些规则应与 `http资产注册.md` 中的注册期校验保持一致。

### 10.3 当前已落地的响应解释扩展

当前版本在 `response_template_json` 下额外支持两个运行时字段：

1. `extractionRules`
2. `successRule`

示例：

```json
{
  "body": "报名状态：{{ extracted.signup_status }}",
  "extractionRules": [
    {
      "key": "signup_status",
      "path": "data.status",
      "required": true
    }
  ],
  "successRule": {
    "path": "data.success",
    "equals": true,
    "errorPath": "data.message"
  }
}
```

语义：

1. `extractionRules` 用于从 JSON 响应里抽取关键字段，返回到 `response.extracted`
2. `successRule` 用于补一层业务成功判定
3. `execute_http_resource` 返回时：
   - `response.protocol_ok` 表示 HTTP / transport 层是否成功
   - `response.business_ok` 表示业务规则是否成功
   - `response.ok` 表示 overall ok；若 `successRule` 判定失败，则会降为 `false`
4. 若 `successRule` 判定失败，`error.type` 会返回 `business_error`

---

## 11. `url_mode=tag` 的前置依赖

当前协议支持：

1. `url_mode=direct`
2. `url_mode=tag`

其中 `direct` 可以直接执行，但 `tag` 模式要想真正跑通，必须补充一个运行时 URL 解析器。

### 11.1 建议新增 `BaseUrlResolver`

职责：

1. 输入：`system_short + sys_label`
2. 输出：对应的 `base_url`

最终执行 URL 生成方式：

1. 若 `url_mode=direct`
   - 使用 `direct_url + url_suffix`
2. 若 `url_mode=tag`
   - 使用 `BaseUrlResolver(system_short, sys_label) + url_suffix`

如果缺少这一层，`tag` 模式只能注册，不能真正执行。

### 11.2 当前实现约定

当前版本已经落地最小 `BaseUrlResolver`，暂不引入新表，直接读取环境变量：

1. 先读 `XAGENT_GDP_HTTP_BASE_URL_<SYSTEM_SHORT>_<SYS_LABEL>`
2. 若未命中，再读 `XAGENT_GDP_HTTP_BASE_URL_<SYSTEM_SHORT>`

例如：

```env
XAGENT_GDP_HTTP_BASE_URL_CRM_PUBLIC=https://crm-public.example.com
XAGENT_GDP_HTTP_BASE_URL_CRM_INTERNAL=https://crm-internal.example.com
XAGENT_GDP_HTTP_BASE_URL_ERP=https://erp.example.com
```

说明：

1. `SYSTEM_SHORT` 和 `SYS_LABEL` 会在运行时转成大写，并把非字母数字字符折叠成下划线
2. 这是一套 MVP 级运维约定，后续若出现集中配置需求，再演进成独立宿主配置表

---

## 12. 返回结果的错误语义

建议 `execute_http_resource` 统一返回可读错误结构，而不是直接把原始异常抛给模型。

建议分三类：

### 12.1 资产级错误

例如：

1. 资源不存在
2. 资源不可见
3. 资源已删除

### 12.2 参数级错误

例如：

1. 缺少必填参数
2. 参数类型不匹配
3. 枚举值非法
4. 正则校验失败

### 12.3 调用级错误

例如：

1. URL 解析失败
2. 网络连接失败
3. 请求超时
4. 上游返回非 2xx
5. 响应模板渲染失败

建议统一包装为：

```json
{
  "resource": {...},
  "request": {...},
  "response": null,
  "error": {
    "type": "parameter_error",
    "message": "缺少必填参数 mobile"
  }
}
```

---

## 13. 工具与模型的交互建议

### 13.1 推荐调用顺序

模型应遵循如下顺序：

1. 先调用 `query_http_resource`
2. 阅读候选资产的 `tool_description`
3. 阅读候选资产的 `input_schema_json`
4. 若参数不足，继续询问用户
5. 参数完整后，再调用 `execute_http_resource`

### 13.2 不建议的行为

模型不应：

1. 在未查询资源前直接猜 `resource_key`
2. 把执行层字段当成自己可编辑输入
3. 自行构造 URL、headers、auth

这些行为会破坏协议封装边界。

---

## 14. 建议新增的内部服务

为了避免把逻辑都堆进现有 CRUD service，建议新增如下服务：

1. `HttpResourceQueryService`
   - 候选资产检索与排序
2. `HttpResourceRuntimeService`
   - 统一执行入口
3. `HttpRuntimeDefinitionAssembler`
   - ORM -> 运行时定义对象
4. `HttpArgumentValidator`
   - 调用期参数校验
5. `HttpRequestAssembler`
   - 参数路由与模板渲染
6. `HttpInvoker`
   - HTTP 执行
7. `HttpResponseInterpreter`
   - 响应折叠与格式化

关键原则：

- CRUD service 继续承担后台管理职责
- Tool 运行时逻辑单独放在运行时服务中

---

## 15. 推荐实施顺序

建议按以下顺序落地：

### Phase 1

1. 实现 `query_http_resource`
2. 实现候选检索、排序、返回完整模型可见层字段

目标：

- 先让模型“能找到接口”

### Phase 2

1. 实现 `HttpRuntimeDefinitionAssembler`
2. 实现 `HttpArgumentValidator`
3. 实现 `HttpRequestAssembler`

目标：

- 先让运行时“能正确组请求”

### Phase 3

1. 实现 `HttpInvoker`
2. 实现 `HttpResponseInterpreter`
3. 实现 `execute_http_resource`

目标：

- 让模型“能真正调用接口并拿到稳定结果”

### Phase 4

1. 增加执行日志
2. 增加调用审计
3. 增加失败原因归档
4. 评估是否补充业务成功判定和响应提取规则

目标：

- 让这套工具链可观测、可排障、可治理

---

## 16. 结论

GDP HTTP 资产的下一阶段，不再是“继续补 CRUD”，而是建立一条完整的“模型发现 -> 模型决策 -> 协议转换 -> HTTP 调用 -> 响应返回”链路。

这条链路最合理的形态不是“直接把每个 HTTP 资产都注册成独立工具”，而是：

1. `query_http_resource`
2. `execute_http_resource`

其中：

- `query_http_resource` 返回候选 HTTP 资产的完整模型可见层定义
- `execute_http_resource` 封装 HTTP 执行层细节，完成真实调用

这样既能继承 `http2mcp` 的协议转换思想，又能保持当前 Xagent 的资产治理边界清晰、实现成本可控。
