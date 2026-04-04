"""GDP HTTP 资产运行时模型。

这组模型不负责落库，也不直接参与 CRUD 请求体校验。
它们专门服务于模型运行时两个动作：

1. `query_http_resource`
   - 把资产检索结果整理成模型容易消费的稳定结构
2. `execute_http_resource`
   - 把资产定义收敛成执行时 definition
   - 把请求快照、响应快照、错误语义统一成单一返回协议

这样做的意义是把“后台注册协议”和“模型运行时协议”明确隔开。
注册协议强调可编辑、可校验；运行时协议强调可执行、可解释、可回放。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HttpToolContractView(BaseModel):
    """模型可见层的稳定投影。

    这里显式保留完整 MCP 可见层字段，原因不是为了复刻数据库结构，
    而是为了保证 `query_http_resource` 返回的每个候选项都能直接被模型拿来做决策：
    - 看 `tool_name` / `tool_description` 判断是不是要的接口
    - 看 `input_schema_json` 判断缺哪些参数
    - 看 `output_schema_json` 与 `annotations_json` 评估调用风险和结果形态
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    tool_description: str
    input_schema_json: dict[str, Any] = Field(default_factory=dict)
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    annotations_json: dict[str, Any] = Field(default_factory=dict)


class HttpResourceMatchContext(BaseModel):
    """候选命中解释。

    运行时并不追求做复杂召回算法，但必须把“为什么命中”显式返回，
    这样后续如果模型选错接口，至少能回溯是检索、排序还是描述文本的问题。
    """

    model_config = ConfigDict(extra="forbid")

    score: float = 0.0
    matched_fields: list[str] = Field(default_factory=list)
    intent_hint: str = "unknown"


class HttpArgumentOutlineItem(BaseModel):
    """输入参数摘要项。

    `query_http_resource` 已经返回完整 `input_schema_json`，但模型在大多数场景里并不想
    一开始就深读整份 JSON Schema。它通常先做两件事：

    1. 判断这是不是自己真正要调用的接口
    2. 判断还缺哪些参数，需要不要继续追问用户

    因此这里补一个“摘要层”，让模型先快速理解顶层参数与关键嵌套参数：
    - `name`：当前参数节点自己的字段名
    - `path`：从 arguments 根节点展开后的稳定路径，便于提示缺参
    - `type` / `description`：帮助模型快速生成追问话术
    - `required`：标记这一层字段在所属对象里是否必填

    约束说明：
    - 它不是 `input_schema_json` 的替代品，只是低成本入口
    - 复杂约束例如 `oneOf` / `allOf` / `patternProperties` 仍然以完整 schema 为准
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    type: str | None = None
    description: str | None = None
    required: bool = False


class HttpResourceQueryItem(BaseModel):
    """单条 HTTP 资产查询结果。

    这个对象既要保留完整 MCP 可见层定义，也要尽量降低模型首轮理解成本。
    所以除了 `tool_contract` 之外，还额外返回参数摘要：

    - `required_argument_names`
      顶层必填参数名列表，用于模型快速判断是否缺关键入参
    - `argument_outline`
      展开后的参数摘要，帮助模型组织下一轮追问或参数填充
    """

    model_config = ConfigDict(extra="forbid")

    resource_id: int
    resource_key: str
    system_short: str
    summary: str | None = None
    tags_json: list[str] = Field(default_factory=list)
    visibility: str
    required_argument_names: list[str] = Field(default_factory=list)
    argument_outline: list[HttpArgumentOutlineItem] = Field(default_factory=list)
    tool_contract: HttpToolContractView
    match_context: HttpResourceMatchContext


class HttpResourceQueryResult(BaseModel):
    """`query_http_resource` 的统一返回结构。"""

    model_config = ConfigDict(extra="forbid")

    items: list[HttpResourceQueryItem] = Field(default_factory=list)
    total: int = 0


class HttpRuntimeDefinition(BaseModel):
    """HTTP 资产运行时 definition。

    这是 ORM 记录进入执行链前的规整化结果：
    - 一侧保留模型可见层，方便结果回传时引用
    - 一侧保留执行层，方便请求组装与 HTTP 调用
    """

    model_config = ConfigDict(extra="forbid")

    resource_id: int
    resource_key: str
    system_short: str
    visibility: str
    tool_contract: HttpToolContractView
    method: str
    url_mode: str
    direct_url: str | None = None
    sys_label: str | None = None
    url_suffix: str | None = None
    args_position_json: dict[str, dict[str, Any]] = Field(default_factory=dict)
    request_template_json: dict[str, Any] = Field(default_factory=dict)
    response_template_json: dict[str, Any] = Field(default_factory=dict)
    error_response_template: str | None = None
    auth_json: dict[str, Any] = Field(default_factory=dict)
    headers_json: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30


class HttpRequestSnapshot(BaseModel):
    """真实发起请求前的快照。

    这个对象既服务 `dry_run`，也服务调试回放。
    它表示“运行时最终打算怎么调用”，而不是数据库里原始配置长什么样。
    """

    model_config = ConfigDict(extra="forbid")

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    json_body: Any | None = None
    text_body: str | None = None


class HttpExecutionResourceRef(BaseModel):
    """执行结果里的资源摘要。"""

    model_config = ConfigDict(extra="forbid")

    resource_id: int
    resource_key: str
    tool_name: str


class HttpExecutionResponse(BaseModel):
    """执行后的响应摘要。"""

    model_config = ConfigDict(extra="forbid")

    status_code: int
    ok: bool
    protocol_ok: bool
    business_ok: bool | None = None
    content_type: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    rendered_text: str


class HttpExecutionError(BaseModel):
    """统一错误语义。

    这里刻意不把 Python 异常对象原样往上传，
    因为模型真正需要的是“哪一层出错了、要不要补参数、还能不能重试”。
    """

    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    details: dict[str, Any] | None = None


class HttpExecuteResult(BaseModel):
    """`execute_http_resource` 的统一返回结构。"""

    model_config = ConfigDict(extra="forbid")

    resource: HttpExecutionResourceRef
    request: HttpRequestSnapshot | None = None
    response: HttpExecutionResponse | None = None
    error: HttpExecutionError | None = None
