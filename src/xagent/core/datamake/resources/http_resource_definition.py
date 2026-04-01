"""
`Resource Plane / HTTP Resource Definition`（资源平面 / HTTP 资源定义）模块。

这个文件只负责两件事：
1. 定义 HTTP 资源协议模型
2. 把运行时 `metadata` 解释成稳定结构

当前阶段只支持新协议格式，不再兼容历史 HTTP 元数据写法。
它明确不负责参数校验、模板渲染、真实 HTTP 调用和结果归一化。
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from ..contracts.constants import ADAPTER_KIND_HTTP
from .registry import ResourceActionDefinition


class HttpDatasourceBinding(BaseModel):
    """
    `HttpDatasourceBinding`（HTTP 数据源层绑定）。

    这里只描述真实请求最终投递到哪里、凭证引用名是什么、超时如何控制，
    不表达接口业务含义。
    """

    base_url: str = Field(default="", description="HTTP 服务基址。")
    auth_type: str = Field(default="none", description="鉴权类型标识。")
    auth_connection_name: str | None = Field(
        default=None,
        description="凭证中心中的连接名。",
    )
    timeout_seconds: float = Field(default=30.0, description="接口超时秒数。")

    def to_metadata_dict(self) -> dict[str, Any]:
        """转成 `metadata['http_datasource']` 使用的稳定字典。"""

        return self.model_dump(mode="json", exclude_none=True)


class HttpContextMaterialSet(BaseModel):
    """
    `HttpContextMaterialSet`（HTTP 上下文材料集）。

    这里放给主脑看的真实样例和口径说明，用于减少自由脑补。
    """

    example_requests: list[str] = Field(default_factory=list, description="请求样例。")
    example_responses: list[str] = Field(default_factory=list, description="响应样例。")
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="字段口径、业务规则和坑点说明。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "HttpContextMaterialSet":
        """从结构化 mapping 恢复上下文材料。"""

        if not isinstance(value, Mapping):
            return cls()
        return cls(
            example_requests=_normalize_string_list(value.get("example_requests")),
            example_responses=_normalize_string_list(value.get("example_responses")),
            documentation_snippets=_normalize_string_list(
                value.get("documentation_snippets")
            ),
        )


class HttpParameterDefinition(BaseModel):
    """
    `HttpParameterDefinition`（HTTP 业务参数定义）。

    这里定义的是“模型要补什么业务参数树”，不是“参数最终写到 HTTP 哪里”。
    参数落点的最终解释权只在 `HttpArgRoute`。
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="参数名。")
    type: Literal["string", "number", "integer", "boolean", "object", "array"] = Field(
        default="string",
        description="参数类型。",
    )
    description: str = Field(default="", description="参数业务说明。")
    required: bool = Field(default=False, description="是否必填。")
    default: Any = Field(default=None, description="默认值。")
    enum: list[Any] | None = Field(default=None, description="可选枚举值。")
    pattern: str | None = Field(default=None, description="正则约束。")
    minimum: float | None = Field(default=None, description="最小值。")
    maximum: float | None = Field(default=None, description="最大值。")
    properties: dict[str, HttpParameterDefinition] | None = Field(
        default=None,
        description="对象参数的子字段定义。",
    )
    items: HttpParameterDefinition | None = Field(
        default=None,
        description="数组元素定义。",
    )


class HttpArgRoute(BaseModel):
    """
    `HttpArgRoute`（HTTP 参数路由规则）。

    这个对象只解释业务参数树中的某个路径最终写入 HTTP 请求的哪里。
    """

    model_config = ConfigDict(populate_by_name=True)

    source_path: str = Field(description="业务参数树中的来源路径。")
    in_: Literal["path", "query", "header", "body"] = Field(
        alias="in",
        description="目标写入位置。",
    )
    name: str | None = Field(default=None, description="目标字段名。")
    array_style: Literal["repeat", "comma", "json"] | None = Field(
        default=None,
        validation_alias=AliasChoices("array_style", "arrayStyle"),
        serialization_alias="arrayStyle",
        description="数组序列化策略。",
    )
    object_style: Literal["json", "flatten"] | None = Field(
        default=None,
        validation_alias=AliasChoices("object_style", "objectStyle"),
        serialization_alias="objectStyle",
        description="对象序列化策略。",
    )

    def to_route_value(self) -> dict[str, Any]:
        """输出 `http_args_position` 的单条 value。"""

        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude={"source_path"},
        )


class HttpHeaderTemplateItem(BaseModel):
    """
    `HttpHeaderTemplateItem`（请求头模板项）。

    用列表而不是 dict，是为了保留顺序并方便前端逐行编辑。
    """

    key: str = Field(description="请求头 key 模板。")
    value: str = Field(description="请求头 value 模板。")


class HttpRequestTemplate(BaseModel):
    """
    `HttpRequestTemplate`（HTTP 请求模板）。

    它只负责“如何拼装请求”，不负责定义业务参数树。
    """

    model_config = ConfigDict(populate_by_name=True)

    url: str | None = Field(default=None, description="完整 URL 模板。")
    method: Literal["GET", "POST"] | None = Field(
        default=None,
        description="请求方法覆盖。",
    )
    headers: list[HttpHeaderTemplateItem] = Field(
        default_factory=list,
        description="结构化请求头模板列表。",
    )
    body: str | None = Field(
        default=None,
        description="完整 JSON Body 模板，渲染后必须可解析。",
    )


class HttpSuccessPolicy(BaseModel):
    """
    `HttpSuccessPolicy`（HTTP 成功判定策略）。

    这里显式拆开协议层成功和业务层成功，避免继续把两种语义混在一起。
    """

    model_config = ConfigDict(populate_by_name=True)

    success_status_codes: list[int] | None = Field(
        default=None,
        description="协议层成功状态码列表；为空表示回退到标准 2xx 成功语义。",
    )
    business_success_path: str | None = Field(default=None, description="业务成功字段路径。")
    business_success_expectation: Any = Field(
        default=None,
        description="业务成功字段的期望值；为空时退化成宽松 truthy 判断。",
    )
    business_error_message_path: str | None = Field(
        default=None,
        description="业务失败时的错误文案路径。",
    )

    @model_validator(mode="after")
    def _validate_success_status_codes(self) -> "HttpSuccessPolicy":
        if self.success_status_codes is not None and not self.success_status_codes:
            raise ValueError("success_status_codes 不能为空")
        return self

    def is_success_status(self, status_code: int) -> bool:
        """
        判断状态码是否命中协议层成功语义。

        关键约束：
        - 若资源显式声明 `success_status_codes`，则以显式列表为准。
        - 若资源未声明，则保持 HTTP 常识语义，统一回退到 `2xx`。
        """

        if self.success_status_codes is not None:
            return status_code in self.success_status_codes
        return 200 <= status_code < 300

    def to_metadata_dict(self) -> dict[str, Any]:
        """转成 `metadata['http_response_success_policy']` 使用的稳定字典。"""

        return self.model_dump(mode="json", exclude_none=True)


class HttpResponseExtractionRule(BaseModel):
    """
    `HttpResponseExtractionRule`（成功响应关键字段提取规则）。

    它负责把真正会影响后续决策的资产字段先抽出来，避免每层重新读厚重响应。
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(description="提取后的规范化字段名。")
    path: str = Field(description="响应体中的字段路径。")
    description: str = Field(default="", description="字段业务含义说明。")
    required: bool = Field(default=False, description="是否要求必须命中。")

    def to_metadata_dict(self) -> dict[str, Any]:
        """转成 `metadata['http_response_extraction_rules']` 使用的稳定字典。"""

        return self.model_dump(mode="json", exclude_none=True)


class HttpResponseTemplate(BaseModel):
    """
    `HttpResponseTemplate`（成功响应模板）。

    它只负责把成功响应翻译成模型可读文本，不负责做成功判定或资产提取。
    """

    model_config = ConfigDict(populate_by_name=True)

    body: str | None = Field(default=None, description="完整覆盖式成功模板。")
    prepend_body: str | None = Field(
        default=None,
        validation_alias=AliasChoices("prepend_body", "prependBody"),
        serialization_alias="prependBody",
        description="默认摘要前追加文本。",
    )
    append_body: str | None = Field(
        default=None,
        validation_alias=AliasChoices("append_body", "appendBody"),
        serialization_alias="appendBody",
        description="默认摘要后追加文本。",
    )

    @model_validator(mode="after")
    def _validate_strategy(self) -> "HttpResponseTemplate":
        if self.body and (self.prepend_body or self.append_body):
            raise ValueError("response_template.body 与 prepend_body/append_body 互斥")
        return self


class HttpToolSafetyHints(BaseModel):
    """
    `HttpToolSafetyHints`（HTTP 工具静态安全提示）。

    这里表达接口自身的静态属性，不直接替代审批决策。
    """

    model_config = ConfigDict(populate_by_name=True)

    read_only_hint: bool = Field(
        default=False,
        validation_alias=AliasChoices("read_only_hint", "readOnlyHint"),
        serialization_alias="readOnlyHint",
        description="是否明显属于只读查询接口。",
    )
    destructive_hint: bool = Field(
        default=False,
        validation_alias=AliasChoices("destructive_hint", "destructiveHint"),
        serialization_alias="destructiveHint",
        description="是否可能触发真实写入、删除、扣费、状态推进。",
    )
    idempotent_hint: bool = Field(
        default=False,
        validation_alias=AliasChoices("idempotent_hint", "idempotentHint"),
        serialization_alias="idempotentHint",
        description="同样请求重复执行是否通常可接受。",
    )


class HttpInterfaceContract(BaseModel):
    """
    `HttpInterfaceContract`（HTTP 接口业务契约）。

    这里沉淀的是主脑理解接口能力所需的最小稳定信息：
    方法、路径、业务意图和业务参数树。
    """

    method: Literal["GET", "POST"] = Field(
        default="POST",
        description="接口方法。首版仅支持 GET / POST。",
    )
    path: str = Field(default="", description="接口路径。")
    business_intent: str = Field(
        default="",
        description="接口业务职责说明，是主脑召回和理解的核心文本。",
    )
    parameters: list[HttpParameterDefinition] = Field(
        default_factory=list,
        description="业务参数树定义。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class HttpEndpointSpec(BaseModel):
    """
    `HttpEndpointSpec`（HTTP 接口目标协议总对象）。

    这是设计文档里的目标顶层模型，方便后续把“完整接口协议”作为单对象传递。
    当前阶段它主要承担协议表达和序列化职责。
    """

    endpoint_id: str = Field(default="", description="接口内部唯一标识。")
    name: str = Field(default="", description="接口可读名称。")
    description: str = Field(default="", description="接口描述。")
    datasource: HttpDatasourceBinding = Field(default_factory=HttpDatasourceBinding)
    interface: HttpInterfaceContract = Field(default_factory=HttpInterfaceContract)
    args_position: list[HttpArgRoute] = Field(default_factory=list)
    request_template: HttpRequestTemplate | None = Field(default=None)
    response_success_policy: HttpSuccessPolicy = Field(default_factory=HttpSuccessPolicy)
    response_template: HttpResponseTemplate | None = Field(default=None)
    error_response_template: str | None = Field(default=None)
    response_extraction_rules: list[HttpResponseExtractionRule] = Field(
        default_factory=list
    )
    safety_hints: HttpToolSafetyHints = Field(default_factory=HttpToolSafetyHints)
    context_materials: HttpContextMaterialSet = Field(
        default_factory=HttpContextMaterialSet
    )


class HttpResolvedResourceMetadata(BaseModel):
    """
    `HttpResolvedResourceMetadata`（HTTP 资源解析后元数据）。

    这是 Guard / Runtime Compiler / Adapter / Normalizer 统一读取的结构化解释结果。
    任何一层都不应该再去手写 `metadata.get("http_xxx")` 猜字段。
    """

    datasource: HttpDatasourceBinding = Field(default_factory=HttpDatasourceBinding)
    contract: HttpInterfaceContract = Field(default_factory=HttpInterfaceContract)
    args_position: list[HttpArgRoute] = Field(default_factory=list)
    request_template: HttpRequestTemplate | None = Field(default=None)
    response_success_policy: HttpSuccessPolicy = Field(default_factory=HttpSuccessPolicy)
    response_template: HttpResponseTemplate | None = Field(default=None)
    error_response_template: str | None = Field(default=None)
    response_extraction_rules: list[HttpResponseExtractionRule] = Field(
        default_factory=list
    )
    safety_hints: HttpToolSafetyHints = Field(default_factory=HttpToolSafetyHints)
    context_materials: HttpContextMaterialSet = Field(
        default_factory=HttpContextMaterialSet
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_mapping(
        cls,
        metadata: Mapping[str, Any] | None,
    ) -> "HttpResolvedResourceMetadata":
        """从新协议 metadata 恢复 HTTP 协议对象。"""

        if not isinstance(metadata, Mapping):
            return cls()

        datasource_raw = _ensure_mapping(metadata.get("http_datasource"))
        contract_raw = _ensure_mapping(metadata.get("http_contract"))
        context_raw = _ensure_mapping(metadata.get("http_context"))
        success_policy_raw = _ensure_mapping(metadata.get("http_response_success_policy"))
        request_template_raw = _ensure_mapping(metadata.get("http_request_template"))
        response_template_raw = _ensure_mapping(metadata.get("http_response_template"))
        safety_hints_raw = _ensure_mapping(metadata.get("http_safety_hints"))
        explicit_extra = metadata.get("extra")
        if not isinstance(explicit_extra, dict):
            explicit_extra = {}

        parameters = _load_http_parameters(contract_raw.get("parameters"))
        response_extraction_rules = _load_http_extraction_rules(
            metadata.get("http_response_extraction_rules")
        )
        response_success_policy = HttpSuccessPolicy.model_validate(success_policy_raw)
        args_position = _load_http_arg_routes(metadata.get("http_args_position"))

        known_keys = {
            "http_datasource",
            "http_contract",
            "http_context",
            "http_args_position",
            "http_request_template",
            "http_response_success_policy",
            "http_response_template",
            "http_error_response_template",
            "http_response_extraction_rules",
            "http_safety_hints",
            "extra",
        }
        unknown_top_level = {
            key: value for key, value in metadata.items() if key not in known_keys
        }

        return cls(
            datasource=HttpDatasourceBinding(
                base_url=_coalesce_str(datasource_raw.get("base_url")) or "",
                auth_type=_coalesce_str(datasource_raw.get("auth_type")) or "none",
                auth_connection_name=_coalesce_str(
                    datasource_raw.get("auth_connection_name")
                ),
                timeout_seconds=_coalesce_float(
                    datasource_raw.get("timeout_seconds"),
                    default=30.0,
                ),
            ),
            contract=HttpInterfaceContract(
                method=_coalesce_method(
                    contract_raw.get("method"),
                    default="POST",
                ),
                path=_coalesce_str(contract_raw.get("path")) or "",
                business_intent=_coalesce_str(contract_raw.get("business_intent")) or "",
                parameters=parameters,
            ),
            args_position=args_position,
            request_template=(
                HttpRequestTemplate.model_validate(request_template_raw)
                if request_template_raw
                else None
            ),
            response_success_policy=response_success_policy,
            response_template=(
                HttpResponseTemplate.model_validate(response_template_raw)
                if response_template_raw
                else None
            ),
            error_response_template=_coalesce_str(
                metadata.get("http_error_response_template")
            ),
            response_extraction_rules=response_extraction_rules,
            safety_hints=HttpToolSafetyHints.model_validate(safety_hints_raw),
            context_materials=HttpContextMaterialSet.from_mapping(context_raw),
            extra={**explicit_extra, **unknown_top_level},
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        输出运行期 `ResourceActionDefinition.metadata` 使用的标准字典。

        这里只写新协议分层字段，不再输出旧协议兼容结构。
        """

        payload: dict[str, Any] = {
            "http_datasource": self.datasource.to_metadata_dict(),
            "http_contract": self.contract.to_metadata_dict(),
            "http_context": self.context_materials.to_metadata_dict(),
            "http_args_position": {
                route.source_path: route.to_route_value() for route in self.args_position
            },
            "http_response_success_policy": self.response_success_policy.to_metadata_dict(),
            "http_response_extraction_rules": [
                rule.to_metadata_dict()
                for rule in self.response_extraction_rules
            ],
            "http_safety_hints": self.safety_hints.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            ),
        }
        if self.request_template is not None:
            payload["http_request_template"] = self.request_template.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        if self.response_template is not None:
            payload["http_response_template"] = self.response_template.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        if self.error_response_template:
            payload["http_error_response_template"] = self.error_response_template
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload

    def to_endpoint_spec(
        self,
        *,
        endpoint_id: str = "",
        name: str = "",
        description: str = "",
    ) -> HttpEndpointSpec:
        """把解析后的 metadata 还原成目标协议顶层对象。"""

        return HttpEndpointSpec(
            endpoint_id=endpoint_id,
            name=name,
            description=description,
            datasource=self.datasource,
            interface=self.contract,
            args_position=list(self.args_position),
            request_template=self.request_template,
            response_success_policy=self.response_success_policy,
            response_template=self.response_template,
            error_response_template=self.error_response_template,
            response_extraction_rules=list(self.response_extraction_rules),
            safety_hints=self.safety_hints,
            context_materials=self.context_materials,
        )


class HttpResourceMetadata(BaseModel):
    """
    `HttpResourceMetadata`（HTTP 资源元数据模板）。

    这个对象面向资源注册方，提供相对扁平、易构造的输入入口，
    但输出时会收敛成 `HttpResolvedResourceMetadata` 的结构化 metadata。
    """

    base_url: str = Field(default="", description="HTTP 服务基址。")
    path: str = Field(default="", description="接口路径。")
    business_intent: str = Field(default="", description="接口业务职责说明。")
    method: Literal["GET", "POST"] = Field(default="POST", description="接口方法。")
    auth_type: str = Field(default="none", description="鉴权类型。")
    auth_connection_name: str | None = Field(default=None, description="凭证中心连接名。")
    timeout_seconds: float = Field(default=30.0, description="接口超时秒数。")
    example_requests: list[str] = Field(default_factory=list)
    example_responses: list[str] = Field(default_factory=list)
    documentation_snippets: list[str] = Field(default_factory=list)
    parameters: list[HttpParameterDefinition] = Field(default_factory=list)
    args_position: list[HttpArgRoute] = Field(
        default_factory=list,
        description="参数路由规则。",
    )
    request_template: HttpRequestTemplate | None = Field(default=None)
    response_success_policy: HttpSuccessPolicy = Field(default_factory=HttpSuccessPolicy)
    response_template: HttpResponseTemplate | None = Field(default=None)
    error_response_template: str | None = Field(default=None)
    response_extraction_rules: list[HttpResponseExtractionRule] = Field(
        default_factory=list
    )
    safety_hints: HttpToolSafetyHints = Field(default_factory=HttpToolSafetyHints)
    extra: dict[str, Any] = Field(default_factory=dict)

    def to_resolved_metadata(self) -> HttpResolvedResourceMetadata:
        """把扁平模板收敛成运行期统一读取的解析对象。"""

        return HttpResolvedResourceMetadata(
            datasource=HttpDatasourceBinding(
                base_url=self.base_url,
                auth_type=self.auth_type,
                auth_connection_name=self.auth_connection_name,
                timeout_seconds=self.timeout_seconds,
            ),
            contract=HttpInterfaceContract(
                method=self.method,
                path=self.path,
                business_intent=self.business_intent,
                parameters=list(self.parameters),
            ),
            args_position=list(self.args_position),
            request_template=self.request_template,
            response_success_policy=self.response_success_policy,
            response_template=self.response_template,
            error_response_template=self.error_response_template,
            response_extraction_rules=list(self.response_extraction_rules),
            safety_hints=self.safety_hints,
            context_materials=HttpContextMaterialSet(
                example_requests=list(self.example_requests),
                example_responses=list(self.example_responses),
                documentation_snippets=list(self.documentation_snippets),
            ),
            extra=dict(self.extra),
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        return self.to_resolved_metadata().to_metadata_dict()


class HttpResourceActionTemplate(BaseModel):
    """
    `HttpResourceActionTemplate`（HTTP 资源动作模板）。

    这是资源注册方最常用的入口：
    - 顶层表达资源动作的治理属性
    - `http_metadata` 表达 HTTP 协议与上下文信息
    """

    resource_key: str = Field(description="资源键。")
    operation_key: str = Field(description="动作键。")
    tool_name: str = Field(
        default="execute_http_api",
        description="底层承载的 xagent 工具名。",
    )
    description: str = Field(
        default="",
        description="动作说明，供主脑理解该动作能完成什么业务。",
    )
    risk_level: str = Field(default="medium", description="静态风险等级。")
    supports_probe: bool = Field(default=False, description="是否支持 probe 探测。")
    requires_approval: bool = Field(default=False, description="是否默认要求审批。")
    result_normalizer: str | None = Field(
        default="http_structured",
        description="绑定的结果归一化器名。",
    )
    result_contract: dict[str, Any] = Field(
        default_factory=dict,
        description="留给 normalizer 的额外结果契约。",
    )
    http_metadata: HttpResourceMetadata = Field(description="HTTP 协议与上下文元数据。")

    def to_resource_action_definition(self) -> ResourceActionDefinition:
        """转成运行期目录里真正注册的资源动作定义。"""

        return ResourceActionDefinition(
            resource_key=self.resource_key,
            operation_key=self.operation_key,
            adapter_kind=ADAPTER_KIND_HTTP,
            tool_name=self.tool_name,
            description=self.description,
            risk_level=self.risk_level,
            supports_probe=self.supports_probe,
            requires_approval=self.requires_approval,
            result_normalizer=self.result_normalizer,
            result_contract=dict(self.result_contract),
            metadata=self.http_metadata.to_metadata_dict(),
        )

    def to_context_payload(self) -> dict[str, Any]:
        """转成可直接塞进 `context.state['datamake_resource_actions']` 的字典。"""

        return self.to_resource_action_definition().__dict__.copy()


def build_http_resource_action_definition(
    *,
    resource_key: str,
    operation_key: str,
    description: str,
    http_metadata: HttpResourceMetadata,
    tool_name: str = "execute_http_api",
    risk_level: str = "medium",
    supports_probe: bool = False,
    requires_approval: bool = False,
    result_normalizer: str | None = "http_structured",
    result_contract: dict[str, Any] | None = None,
) -> ResourceActionDefinition:
    """快速构造标准 HTTP 资源动作定义。"""

    template = HttpResourceActionTemplate(
        resource_key=resource_key,
        operation_key=operation_key,
        tool_name=tool_name,
        description=description,
        risk_level=risk_level,
        supports_probe=supports_probe,
        requires_approval=requires_approval,
        result_normalizer=result_normalizer,
        result_contract=result_contract or {},
        http_metadata=http_metadata,
    )
    return template.to_resource_action_definition()


def build_http_resource_action_payload(
    *,
    resource_key: str,
    operation_key: str,
    description: str,
    http_metadata: HttpResourceMetadata,
    tool_name: str = "execute_http_api",
    risk_level: str = "medium",
    supports_probe: bool = False,
    requires_approval: bool = False,
    result_normalizer: str | None = "http_structured",
    result_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """快速构造 `datamake_resource_actions` 使用的 HTTP 资源负载。"""

    template = HttpResourceActionTemplate(
        resource_key=resource_key,
        operation_key=operation_key,
        tool_name=tool_name,
        description=description,
        risk_level=risk_level,
        supports_probe=supports_probe,
        requires_approval=requires_approval,
        result_normalizer=result_normalizer,
        result_contract=result_contract or {},
        http_metadata=http_metadata,
    )
    return template.to_context_payload()


def parse_http_resource_metadata(
    metadata: Mapping[str, Any] | None,
) -> HttpResolvedResourceMetadata:
    """
    统一解析 HTTP 资源元数据。

    这是 Guard / Runtime Compiler / Adapter / Normalizer 的唯一入口，
    目的是避免每层重新解释一遍协议字典。
    """

    return HttpResolvedResourceMetadata.from_mapping(metadata)


def _ensure_mapping(value: Any) -> Mapping[str, Any]:
    """把不稳定输入收敛成 mapping。"""

    if isinstance(value, Mapping):
        return value
    return {}


def _load_http_parameters(value: Any) -> list[HttpParameterDefinition]:
    """宽松恢复参数定义列表。"""

    if not isinstance(value, list):
        return []
    parameters: list[HttpParameterDefinition] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        parameters.append(HttpParameterDefinition.model_validate(item))
    return parameters


def _load_http_arg_routes(
    value: Any,
) -> list[HttpArgRoute]:
    """
    恢复参数路由规则。
    """

    routes: list[HttpArgRoute] = []
    if isinstance(value, Mapping):
        for source_path, route_value in value.items():
            if not isinstance(route_value, Mapping):
                continue
            payload = dict(route_value)
            payload["source_path"] = str(source_path)
            routes.append(HttpArgRoute.model_validate(payload))
        return routes

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, Mapping):
                continue
            routes.append(HttpArgRoute.model_validate(item))
        return routes

    return []


def _load_http_extraction_rules(value: Any) -> list[HttpResponseExtractionRule]:
    """宽松恢复关键字段提取规则。"""

    if not isinstance(value, list):
        return []
    rules: list[HttpResponseExtractionRule] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        rules.append(HttpResponseExtractionRule.model_validate(item))
    return rules


def _normalize_string_list(value: Any) -> list[str]:
    """把不稳定输入收敛成 `list[str]`。"""

    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _coalesce_str(*values: Any) -> str | None:
    """返回第一个非空字符串。"""

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coalesce_float(*values: Any, default: float) -> float:
    """返回第一个可解释为浮点数的值。"""

    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return default


def _coalesce_method(
    *values: Any,
    default: Literal["GET", "POST"],
) -> Literal["GET", "POST"]:
    """返回第一个合法 HTTP 方法。"""

    for value in values:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"GET", "POST"}:
                return normalized
    return default


HttpParameterDefinition.model_rebuild()
