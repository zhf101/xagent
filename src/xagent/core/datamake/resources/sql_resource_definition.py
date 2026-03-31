"""
`Resource Plane / SQL Resource Definition`（资源平面 / SQL 资源定义）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`（资源平面）
- 在你的设计里：SQL 受控资源动作的注册模板层

这个文件负责什么：
- 给 SQL 资源动作提供一套标准、可读、可校验的注册模板
- 把散落在 `metadata` 里的 SQL 配置项收敛成结构化对象
- 同时定义 Guard 写给 Runtime 的 SQL 上下文快照契约
- 让 Guard / Probe / OpenViking / Orchestrator 都走同一套 schema 读取入口

这个文件不负责什么：
- 不做 SQL 生成
- 不做审批判断
- 不直接执行 SQL
- 不决定“下一步业务动作”

设计原因：
- 仅仅把字段继续平铺在 `metadata` 顶层，会让接入方到处写
  `metadata.get("xxx")`，后续维护会退化成“猜字典”。
- 因此这里把资源元数据拆成三个明确的小契约：
  1. `SqlDatasourceBinding`（SQL 数据源绑定）
  2. `SqlContextMaterialSet`（SQL 上下文材料集）
  3. `OpenVikingContextBinding`（OpenViking 上下文绑定）
- 同时保留对旧平铺字段的兼容解析，避免现有任务声明和历史数据立刻失效。
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field

from ..contracts.constants import ADAPTER_KIND_SQL
from .registry import ResourceActionDefinition


class SqlDatasourceBinding(BaseModel):
    """
    `SqlDatasourceBinding`（SQL 数据源绑定）。

    这个对象只描述“这条 SQL 资源该连到哪里、以什么只读边界访问”，
    不表达业务动作本身。
    """

    connection_name: str | None = Field(
        default=None,
        description="现有 SQL 工具使用的连接名，对应 XAGENT_EXTERNAL_DB_<NAME>。",
    )
    datasource_id: int | None = Field(
        default=None,
        description="宿主侧 datasource 标识。Phase 1 可用于解析 Text2SQLDatabase 配置。",
    )
    text2sql_database_id: int | None = Field(
        default=None,
        description="Text2SQLDatabase 主键。与 datasource_id 语义接近，保留显式字段便于迁移过渡。",
    )
    db_url: str | None = Field(
        default=None,
        description="显式数据库连接串。主要用于受控直连场景，不建议在上层广泛散落使用。",
    )
    db_type: str | None = Field(
        default=None,
        description="数据库类型，例如 postgresql / mysql / sqlite。",
    )
    read_only: bool = Field(
        default=True,
        description="是否只允许只读 SQL。这个字段会直接影响 verify / probe / execute 的安全策略。",
    )
    datasource_name: str | None = Field(
        default=None,
        description="可读的数据源名称，主要用于展示与调试。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        转成适合写入 `metadata["sql_datasource"]` 的结构化字典。
        """

        return self.model_dump(mode="json", exclude_none=True)


class SqlContextMaterialSet(BaseModel):
    """
    `SqlContextMaterialSet`（SQL 上下文材料集）。

    这里收纳的是 SQL Brain 可消费的技术材料，
    而不是治理决策。
    """

    schema_ddl: list[str] = Field(
        default_factory=list,
        description="显式 schema DDL 片段。若存在，应优先于自动反射结果使用。",
    )
    example_sqls: list[str] = Field(
        default_factory=list,
        description="few-shot SQL 示例，用于生成与修复，不参与放行裁决。",
    )
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="口径、字段释义、业务规则等文本片段，用于提升 SQL 规划质量。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        转成适合写入 `metadata["sql_context"]` 的结构化字典。
        """

        return self.model_dump(mode="json")

    def has_any_material(self) -> bool:
        """
        判断当前材料集是否至少包含一类有效材料。
        """

        return bool(
            self.schema_ddl or self.example_sqls or self.documentation_snippets
        )

    def merge(self, extra: "SqlContextMaterialSet") -> "SqlContextMaterialSet":
        """
        以“原始优先、补充追加”的方式合并两份材料集。
        """

        return SqlContextMaterialSet(
            schema_ddl=_merge_unique_strings(self.schema_ddl, extra.schema_ddl),
            example_sqls=_merge_unique_strings(self.example_sqls, extra.example_sqls),
            documentation_snippets=_merge_unique_strings(
                self.documentation_snippets,
                extra.documentation_snippets,
            ),
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "SqlContextMaterialSet":
        """
        从宽松 mapping 恢复材料集。

        这个入口既给 resource metadata 用，也给 execution_action.params.sql_context 用。
        """

        if not isinstance(value, Mapping):
            return cls()
        return cls(
            schema_ddl=_normalize_string_list(value.get("schema_ddl")),
            example_sqls=_normalize_string_list(value.get("example_sqls")),
            documentation_snippets=_normalize_string_list(
                value.get("documentation_snippets")
            ),
        )


class SqlContextHintSource(BaseModel):
    """
    `SqlContextHintSource`（SQL 上下文提示来源）。

    这里记录的是“这份 hint 从哪条 recall/memory 来”，
    供主脑理解提示来源，但不把它升级成事实。
    """

    source_type: str = Field(
        default="memory_recall",
        description="提示来源类型。当前阶段主要是 memory_recall。",
    )
    source_id: str | None = Field(
        default=None,
        description="来源记录标识，例如 memory_id。",
    )
    match_reason: str = Field(
        default="generic_sql",
        description="为什么这条提示会命中当前资源。",
    )
    summary: str | None = Field(
        default=None,
        description="给主脑看的简短来源摘要。",
    )


class SqlContextHintPayload(BaseModel):
    """
    `SqlContextHintPayload`（SQL 上下文提示载荷）。

    这是 DecisionBuilder 提供给主脑的“可选提示”，不是系统强制事实。
    主脑如果决定采用，必须显式写回 `execution_action.params.sql_context`。
    """

    sql_context: SqlContextMaterialSet = Field(
        default_factory=SqlContextMaterialSet,
        description="建议主脑可选带入的 SQL 材料。",
    )
    sources: list[SqlContextHintSource] = Field(
        default_factory=list,
        description="这份提示来自哪些 recall / memory 记录。",
    )


class OpenVikingContextBinding(BaseModel):
    """
    `OpenVikingContextBinding`（OpenViking 上下文绑定）。

    这个对象只表达“如果要去 OpenViking 补技术材料，该拿什么去找”，
    不表达审批、执行或下一步业务意图。
    """

    uri: str | None = Field(
        default=None,
        description="显式 OpenViking 资源 URI。若存在，优先走 read_context。",
    )
    asset_uri: str | None = Field(
        default=None,
        description="兼容别名形式的资产 URI。",
    )
    source: str | None = Field(
        default=None,
        description="OpenViking 搜索目标源。",
    )
    target_uri: str | None = Field(
        default=None,
        description="OpenViking 搜索时的目标 URI。",
    )
    asset_key: str | None = Field(
        default=None,
        description="OpenViking 资产键。没有显式 URI 时，可作为搜索 query。",
    )
    query: str | None = Field(
        default=None,
        description="兼容别名形式的查询词。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        转成适合写入 `metadata["openviking_context"]` 的结构化字典。
        """

        return self.model_dump(mode="json", exclude_none=True)


class SqlContextProviderTrace(BaseModel):
    """
    `SqlContextProviderTrace`（SQL 上下文提供器轨迹）。

    这里记录 provider 成功补充了什么，供账本 / UI / 排障使用。
    """

    provider_name: str = Field(description="provider 名称。")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="该 provider 的技术补充元数据。",
    )


class SqlContextProviderError(BaseModel):
    """
    `SqlContextProviderError`（SQL 上下文提供器错误）。

    provider 失败只能留下技术事实，不能改写控制流。
    """

    provider_name: str = Field(description="失败的 provider 名称。")
    error: str = Field(description="降级后的错误摘要。")


class SqlPreparedContextPayload(BaseModel):
    """
    `SqlPreparedContextPayload`（SQL 预备上下文快照）。

    这是 Guard 写给 Runtime 的系统内部快照，目的是：
    - 让 Probe / Runtime 明确知道当前 SQL Brain 实际吃到了哪些材料
    - 避免继续用匿名 `_system_sql_context` 字典拼来拼去
    """

    example_sqls: list[str] = Field(
        default_factory=list,
        description="当前轮最终可见的示例 SQL 列表。",
    )
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="当前轮最终可见的文档片段列表。",
    )
    context_sources: list[SqlContextHintSource] = Field(
        default_factory=list,
        description=(
            "本轮最终被主脑显式采用的 SQL 上下文来源。"
            "这些来源通常来自 recall hint，而不是系统自动认定事实。"
        ),
    )
    provider_traces: list[SqlContextProviderTrace] = Field(
        default_factory=list,
        description="成功 provider 的轨迹信息。",
    )
    provider_errors: list[SqlContextProviderError] = Field(
        default_factory=list,
        description="provider 失败轨迹。失败只记录，不阻断主链。",
    )

    @classmethod
    def from_prepared_context(cls, prepared_context: Any) -> "SqlPreparedContextPayload":
        """
        从已增强的 `SqlPlanContext` 提取 Runtime 可消费的系统快照。
        """

        metadata = getattr(prepared_context, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        provider_traces: list[SqlContextProviderTrace] = []
        for key, value in metadata.items():
            if not isinstance(key, str) or not key.startswith("provider:"):
                continue
            provider_name = key.split(":", 1)[1]
            provider_traces.append(
                SqlContextProviderTrace(
                    provider_name=provider_name,
                    metadata=value if isinstance(value, dict) else {},
                )
            )

        provider_errors: list[SqlContextProviderError] = []
        raw_errors = metadata.get("sql_context_provider_errors", [])
        if isinstance(raw_errors, list):
            for item in raw_errors:
                if not isinstance(item, dict):
                    continue
                provider_errors.append(
                    SqlContextProviderError(
                        provider_name=str(item.get("provider") or "unknown"),
                        error=str(item.get("error") or ""),
                    )
                )

        return cls(
            example_sqls=list(getattr(prepared_context, "example_sqls", []) or []),
            documentation_snippets=list(
                getattr(prepared_context, "documentation_snippets", []) or []
            ),
            context_sources=[],
            provider_traces=provider_traces,
            provider_errors=provider_errors,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "SqlPreparedContextPayload":
        """
        从 `_system_sql_context` 字典恢复结构化快照。

        兼容旧格式：
        - 旧实现只写 `example_sqls / documentation_snippets`
        - 新实现会额外写 provider 轨迹和错误列表
        """

        if not isinstance(value, Mapping):
            return cls()

        provider_traces = cls._load_provider_traces(value.get("provider_traces"))
        provider_errors = cls._load_provider_errors(value.get("provider_errors"))
        return cls(
            example_sqls=_normalize_string_list(value.get("example_sqls")),
            documentation_snippets=_normalize_string_list(
                value.get("documentation_snippets")
            ),
            context_sources=cls._load_context_sources(value.get("context_sources")),
            provider_traces=provider_traces,
            provider_errors=provider_errors,
        )

    @staticmethod
    def _load_provider_traces(value: Any) -> list[SqlContextProviderTrace]:
        """
        把 provider 轨迹容器恢复成结构化列表。
        """

        if not isinstance(value, list):
            return []
        traces: list[SqlContextProviderTrace] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            traces.append(
                SqlContextProviderTrace(
                    provider_name=str(item.get("provider_name") or "unknown"),
                    metadata=item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {},
                )
            )
        return traces

    @staticmethod
    def _load_provider_errors(value: Any) -> list[SqlContextProviderError]:
        """
        把 provider 错误容器恢复成结构化列表。
        """

        if not isinstance(value, list):
            return []
        errors: list[SqlContextProviderError] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            errors.append(
                SqlContextProviderError(
                    provider_name=str(item.get("provider_name") or "unknown"),
                    error=str(item.get("error") or ""),
                )
            )
        return errors

    @staticmethod
    def _load_context_sources(value: Any) -> list[SqlContextHintSource]:
        """
        把上下文来源容器恢复成结构化列表。
        """

        if not isinstance(value, list):
            return []
        sources: list[SqlContextHintSource] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            sources.append(
                SqlContextHintSource(
                    source_type=str(item.get("source_type") or "memory_recall"),
                    source_id=_coalesce_str(item.get("source_id")),
                    match_reason=str(item.get("match_reason") or "generic_sql"),
                    summary=_coalesce_str(item.get("summary")),
                )
            )
        return sources


class SqlResolvedResourceMetadata(BaseModel):
    """
    `SqlResolvedResourceMetadata`（SQL 资源解析后元数据）。

    它不是给调用方直接手写的模板，而是给运行期各层统一读取的“解释结果”：
    - 能兼容旧平铺字段
    - 能消费新结构化 metadata
    - 让 Guard / Probe / Provider 不再各自猜字典
    """

    sql_brain_enabled: bool = Field(
        default=False,
        description="是否启用 SQL Brain 技术链。只有显式打开后才进入 SQL Brain 预处理链。",
    )
    datasource: SqlDatasourceBinding = Field(
        default_factory=SqlDatasourceBinding,
        description="SQL 数据源绑定信息。",
    )
    sql_context: SqlContextMaterialSet = Field(
        default_factory=SqlContextMaterialSet,
        description="SQL Brain 可见的技术材料。",
    )
    openviking: OpenVikingContextBinding = Field(
        default_factory=OpenVikingContextBinding,
        description="OpenViking 外部上下文绑定信息。",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="未识别的额外扩展信息。只承载技术配置，不承载业务决策。",
    )

    @classmethod
    def from_mapping(
        cls,
        metadata: Mapping[str, Any] | None,
    ) -> "SqlResolvedResourceMetadata":
        """
        兼容读取旧平铺字段和新结构化 metadata。
        """

        if not isinstance(metadata, Mapping):
            return cls()

        sql_datasource_raw = metadata.get("sql_datasource")
        if not isinstance(sql_datasource_raw, Mapping):
            sql_datasource_raw = {}
        sql_context_raw = metadata.get("sql_context")
        if not isinstance(sql_context_raw, Mapping):
            sql_context_raw = {}
        openviking_raw = metadata.get("openviking_context")
        if not isinstance(openviking_raw, Mapping):
            openviking_raw = {}
        explicit_extra = metadata.get("extra")
        if not isinstance(explicit_extra, dict):
            explicit_extra = {}

        known_keys = {
            "sql_brain_enabled",
            "sql_datasource",
            "sql_context",
            "openviking_context",
            "extra",
            "schema_snapshot",
            "ddl_snippets",
            "database_url",
            "database_type",
            "database_name",
            "db_url",
            "db_type",
            "read_only",
            "connection_name",
            "datasource_id",
            "text2sql_database_id",
            "schema_ddl",
            "example_sqls",
            "documentation_snippets",
            "openviking_uri",
            "openviking_asset_uri",
            "openviking_source",
            "openviking_target_uri",
            "openviking_asset_key",
            "openviking_query",
        }

        unknown_top_level = {
            key: value
            for key, value in metadata.items()
            if key not in known_keys and not str(key).startswith("provider:")
        }

        datasource = SqlDatasourceBinding(
            connection_name=_coalesce_str(
                sql_datasource_raw.get("connection_name"),
                metadata.get("connection_name"),
            ),
            datasource_id=_coalesce_int(
                sql_datasource_raw.get("datasource_id"),
                metadata.get("datasource_id"),
            ),
            text2sql_database_id=_coalesce_int(
                sql_datasource_raw.get("text2sql_database_id"),
                metadata.get("text2sql_database_id"),
                metadata.get("database_id"),
            ),
            db_url=_coalesce_str(
                sql_datasource_raw.get("db_url"),
                metadata.get("db_url"),
                metadata.get("database_url"),
            ),
            db_type=_coalesce_str(
                sql_datasource_raw.get("db_type"),
                metadata.get("db_type"),
                metadata.get("database_type"),
            ),
            read_only=_coalesce_bool(
                sql_datasource_raw.get("read_only"),
                metadata.get("read_only"),
                default=True,
            ),
            datasource_name=_coalesce_str(
                sql_datasource_raw.get("datasource_name"),
                metadata.get("database_name"),
            ),
        )
        sql_context = SqlContextMaterialSet(
            schema_ddl=_normalize_string_list(
                sql_context_raw.get("schema_ddl") or metadata.get("schema_ddl")
            ),
            example_sqls=_normalize_string_list(
                sql_context_raw.get("example_sqls") or metadata.get("example_sqls")
            ),
            documentation_snippets=_normalize_string_list(
                sql_context_raw.get("documentation_snippets")
                or metadata.get("documentation_snippets")
            ),
        )
        openviking = OpenVikingContextBinding(
            uri=_coalesce_str(
                openviking_raw.get("uri"),
                metadata.get("openviking_uri"),
            ),
            asset_uri=_coalesce_str(
                openviking_raw.get("asset_uri"),
                metadata.get("openviking_asset_uri"),
            ),
            source=_coalesce_str(
                openviking_raw.get("source"),
                metadata.get("openviking_source"),
            ),
            target_uri=_coalesce_str(
                openviking_raw.get("target_uri"),
                metadata.get("openviking_target_uri"),
            ),
            asset_key=_coalesce_str(
                openviking_raw.get("asset_key"),
                metadata.get("openviking_asset_key"),
            ),
            query=_coalesce_str(
                openviking_raw.get("query"),
                metadata.get("openviking_query"),
            ),
        )

        extra = dict(explicit_extra)
        extra.update(unknown_top_level)
        for passthrough_key in ("schema_snapshot", "ddl_snippets"):
            if passthrough_key in metadata:
                extra[passthrough_key] = metadata[passthrough_key]

        return cls(
            sql_brain_enabled=bool(metadata.get("sql_brain_enabled", False)),
            datasource=datasource,
            sql_context=sql_context,
            openviking=openviking,
            extra=extra,
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        转成运行期 `ResourceActionDefinition.metadata` 使用的结构化字典。
        """

        payload: dict[str, Any] = {
            "sql_brain_enabled": self.sql_brain_enabled,
            "sql_datasource": self.datasource.to_metadata_dict(),
            "sql_context": self.sql_context.to_metadata_dict(),
        }
        openviking_payload = self.openviking.to_metadata_dict()
        if openviking_payload:
            payload["openviking_context"] = openviking_payload
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


class SqlResourceMetadata(BaseModel):
    """
    `SqlResourceMetadata`（SQL 资源元数据模板）。

    这是给调用方声明 SQL 资源动作时使用的输入模板。
    它保留较平滑的构造方式，但输出时会自动收敛成更清晰的结构化 metadata。
    """

    sql_brain_enabled: bool = Field(
        default=True,
        description="是否启用 SQL Brain 技术链。未启用时，SQL 资源仍可按传统方式直接执行。",
    )
    read_only: bool = Field(
        default=True,
        description="是否只允许只读 SQL。这个字段会直接影响 verify / probe / execute 的安全策略。",
    )
    db_type: str | None = Field(
        default=None,
        description="数据库类型，例如 postgresql / mysql / sqlite。",
    )
    connection_name: str | None = Field(
        default=None,
        description="现有 SQL 工具使用的连接名，对应 XAGENT_EXTERNAL_DB_<NAME>。",
    )
    datasource_id: int | None = Field(
        default=None,
        description="宿主侧 datasource 标识。Phase 1 可用于解析 Text2SQLDatabase 配置。",
    )
    text2sql_database_id: int | None = Field(
        default=None,
        description="Text2SQLDatabase 主键。与 datasource_id 语义接近，保留显式字段便于迁移过渡。",
    )
    db_url: str | None = Field(
        default=None,
        description="显式数据库连接串。主要用于受控直连场景，不建议在上层广泛散落使用。",
    )
    schema_ddl: list[str] = Field(
        default_factory=list,
        description="显式 schema DDL 片段。若存在，应优先于自动反射结果使用。",
    )
    example_sqls: list[str] = Field(
        default_factory=list,
        description="few-shot SQL 示例，用于生成与修复，不参与放行裁决。",
    )
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="口径、字段释义、业务规则等文本片段，用于提升 SQL 规划质量。",
    )
    openviking_uri: str | None = Field(
        default=None,
        description="显式 OpenViking 资源 URI。若存在，优先走 read_context。",
    )
    openviking_asset_uri: str | None = Field(
        default=None,
        description="兼容别名形式的资产 URI。",
    )
    openviking_source: str | None = Field(
        default=None,
        description="OpenViking 搜索目标源。",
    )
    openviking_target_uri: str | None = Field(
        default=None,
        description="OpenViking 搜索时的目标 URI。",
    )
    openviking_asset_key: str | None = Field(
        default=None,
        description="OpenViking 资产键。没有显式 URI 时，可作为搜索 query。",
    )
    openviking_query: str | None = Field(
        default=None,
        description="兼容别名形式的查询词。",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="额外元数据扩展位。只承载技术配置，不承载业务决策。",
    )

    def to_metadata_dict(self) -> dict[str, Any]:
        """
        转成可写入 `ResourceActionDefinition.metadata` 的标准字典。
        """

        resolved = SqlResolvedResourceMetadata(
            sql_brain_enabled=self.sql_brain_enabled,
            datasource=SqlDatasourceBinding(
                connection_name=self.connection_name,
                datasource_id=self.datasource_id,
                text2sql_database_id=self.text2sql_database_id,
                db_url=self.db_url,
                db_type=self.db_type,
                read_only=self.read_only,
            ),
            sql_context=SqlContextMaterialSet(
                schema_ddl=list(self.schema_ddl),
                example_sqls=list(self.example_sqls),
                documentation_snippets=list(self.documentation_snippets),
            ),
            openviking=OpenVikingContextBinding(
                uri=self.openviking_uri,
                asset_uri=self.openviking_asset_uri,
                source=self.openviking_source,
                target_uri=self.openviking_target_uri,
                asset_key=self.openviking_asset_key,
                query=self.openviking_query,
            ),
            extra=dict(self.extra),
        )
        return resolved.to_metadata_dict()


class SqlResourceActionTemplate(BaseModel):
    """
    `SqlResourceActionTemplate`（SQL 资源动作模板）。

    这个对象是“可读性更好的 SQL 资源注册入口”。
    它让你在声明一个 SQL 资源动作时，能清晰区分：
    - 顶层资源动作属性
    - SQL Brain / datasource / schema 相关元数据
    """

    resource_key: str = Field(description="资源键。对应你的受控 SQL 资源宿主。")
    operation_key: str = Field(description="动作键。对应这个 SQL 资源暴露的受控操作。")
    tool_name: str = Field(
        default="execute_sql_query",
        description="底层 xagent SQL 工具名。Phase 1 默认沿用 execute_sql_query。",
    )
    description: str = Field(
        default="",
        description="动作说明。应让主脑能理解这个 SQL 资源是做什么的。",
    )
    risk_level: str = Field(
        default="low",
        description="资源定义的基础风险等级。Guard 会与主脑风险、SQL 静态风险合并取高。",
    )
    supports_probe: bool = Field(
        default=True,
        description="是否支持 probe。SQL 资源一般建议开启，以便先走无副作用探测。",
    )
    requires_approval: bool = Field(
        default=False,
        description="是否默认需要审批。高风险 SQL 场景一般建议显式打开。",
    )
    result_normalizer: str | None = Field(
        default=None,
        description="结果归一化器名。SQL 默认通常走 passthrough。",
    )
    result_contract: dict[str, Any] = Field(
        default_factory=dict,
        description="资源结果契约。供 normalizer 解释底层工具返回结构。",
    )
    sql_metadata: SqlResourceMetadata = Field(
        default_factory=SqlResourceMetadata,
        description="SQL 专属元数据配置。",
    )

    def to_resource_action_definition(self) -> ResourceActionDefinition:
        """
        转成运行期真正使用的 `ResourceActionDefinition`。
        """

        return ResourceActionDefinition(
            resource_key=self.resource_key,
            operation_key=self.operation_key,
            adapter_kind=ADAPTER_KIND_SQL,
            tool_name=self.tool_name,
            description=self.description,
            risk_level=self.risk_level,
            supports_probe=self.supports_probe,
            requires_approval=self.requires_approval,
            result_normalizer=self.result_normalizer,
            result_contract=dict(self.result_contract),
            metadata=self.sql_metadata.to_metadata_dict(),
        )

    def to_context_payload(self) -> dict[str, Any]:
        """
        转成可直接放入 `context.state["datamake_resource_actions"]` 的字典。
        """

        return self.to_resource_action_definition().__dict__.copy()


def build_sql_resource_action_definition(
    *,
    resource_key: str,
    operation_key: str,
    description: str,
    sql_metadata: SqlResourceMetadata | None = None,
    tool_name: str = "execute_sql_query",
    risk_level: str = "low",
    supports_probe: bool = True,
    requires_approval: bool = False,
    result_normalizer: str | None = None,
    result_contract: dict[str, Any] | None = None,
) -> ResourceActionDefinition:
    """
    快速构造 SQL 资源动作定义。

    这是给调用方用的便捷入口。
    如果你只想快速声明一个标准 SQL 资源动作，而不想手写整段字典，
    可以直接使用这个函数。
    """

    template = SqlResourceActionTemplate(
        resource_key=resource_key,
        operation_key=operation_key,
        tool_name=tool_name,
        description=description,
        risk_level=risk_level,
        supports_probe=supports_probe,
        requires_approval=requires_approval,
        result_normalizer=result_normalizer,
        result_contract=result_contract or {},
        sql_metadata=sql_metadata or SqlResourceMetadata(),
    )
    return template.to_resource_action_definition()


def build_sql_resource_action_payload(
    *,
    resource_key: str,
    operation_key: str,
    description: str,
    sql_metadata: SqlResourceMetadata | None = None,
    tool_name: str = "execute_sql_query",
    risk_level: str = "low",
    supports_probe: bool = True,
    requires_approval: bool = False,
    result_normalizer: str | None = None,
    result_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    快速构造 `datamake_resource_actions` 可用的字典负载。
    """

    template = SqlResourceActionTemplate(
        resource_key=resource_key,
        operation_key=operation_key,
        tool_name=tool_name,
        description=description,
        risk_level=risk_level,
        supports_probe=supports_probe,
        requires_approval=requires_approval,
        result_normalizer=result_normalizer,
        result_contract=result_contract or {},
        sql_metadata=sql_metadata or SqlResourceMetadata(),
    )
    return template.to_context_payload()


def parse_sql_resource_metadata(
    metadata: Mapping[str, Any] | None,
) -> SqlResolvedResourceMetadata:
    """
    统一解析 SQL 资源元数据。

    这是 Guard / Probe / Provider / Orchestrator 的统一入口，
    目的是避免每层各自手写一套 `metadata.get(...)` 逻辑。
    """

    return SqlResolvedResourceMetadata.from_mapping(metadata)


def _normalize_string_list(value: Any) -> list[str]:
    """
    把不稳定输入统一收敛成 `list[str]`。
    """

    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _merge_unique_strings(base: list[str], extra: list[str]) -> list[str]:
    """
    合并两个字符串列表并去重，保持原顺序优先。
    """

    merged = list(base)
    for item in extra:
        if item not in merged:
            merged.append(item)
    return merged


def _coalesce_str(*values: Any) -> str | None:
    """
    返回第一个非空字符串。
    """

    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coalesce_int(*values: Any) -> int | None:
    """
    返回第一个可解释成 int 的值。
    """

    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _coalesce_bool(*values: Any, default: bool) -> bool:
    """
    返回第一个显式布尔值；若都没有，则回退默认值。
    """

    for value in values:
        if isinstance(value, bool):
            return value
    return default
