"""
`Probe Execution`（探测执行）模块。

这里要特别守住一个边界：
`probe`（探测执行）不是“先偷偷执行一次正式动作”，而是“在不触发真实副作用的前提下，
验证这次动作是否具备进入正式执行的技术条件”。
"""

from __future__ import annotations

from ..contracts.constants import ADAPTER_KIND_SQL, RUNTIME_STATUS_FAILED, RUNTIME_STATUS_SUCCESS
from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from ..resources.catalog import ResourceCatalog
from ..resources.sql_datasource_resolver import SqlDatasourceResolver
from ..resources.sql_brain_gateway import SqlBrainGateway
from ..resources.sql_resource_definition import (
    SqlPreparedContextPayload,
    parse_sql_resource_metadata,
)
from ..contracts.sql_plan import SqlPlanContext, SqlProbeTarget


class ProbeExecutor:
    """
    `ProbeExecutor`（探测执行器）。
    """

    def __init__(
        self,
        resource_catalog: ResourceCatalog,
        sql_brain_gateway: SqlBrainGateway | None = None,
        sql_datasource_resolver: SqlDatasourceResolver | None = None,
    ) -> None:
        self.resource_catalog = resource_catalog
        self.sql_brain_gateway = sql_brain_gateway
        self.sql_datasource_resolver = sql_datasource_resolver or SqlDatasourceResolver()

    async def execute(self, contract: CompiledExecutionContract) -> RuntimeResult:
        """
        执行一个探测契约。
        """

        resource_action = self.resource_catalog.get_action(
            contract.resource_key, contract.operation_key
        )
        # Probe 只验证“有没有能力正式进入执行”，不实际触发 SQL / HTTP / Dubbo 调用。
        # 否则对带副作用的资源动作来说，probe 阶段就会产生真实写入或外部调用。
        if not resource_action.supports_probe:
            return RuntimeResult(
                run_id=contract.run_id,
                status="failed",
                summary="当前资源动作不支持 probe 探测执行",
                facts={
                    "transport_status": "unknown",
                    "protocol_status": "unknown",
                    "business_status": "unknown",
                    "probe_supported": False,
                },
                error="probe_not_supported",
                evidence=[f"resource:{contract.resource_key}/{contract.operation_key}"],
            )

        if self._should_use_sql_brain(resource_action, contract):
            return await self._probe_with_sql_brain(contract)

        # 这里最多做工具存在性和契约完整性确认，不触发真实底层调用。
        self.resource_catalog.get_tool(contract.tool_name)

        return RuntimeResult(
            run_id=contract.run_id,
            status="success",
            summary="Probe 探测校验通过，未触发真实资源调用",
            facts={
                "transport_status": "unknown",
                "protocol_status": "unknown",
                "business_status": "unknown",
                "probe_supported": True,
                "probe_only": True,
            },
            data={
                "probe_only": True,
                "resource_key": contract.resource_key,
                "operation_key": contract.operation_key,
                "adapter_kind": resource_action.adapter_kind,
            },
            evidence=[f"tool:{contract.tool_name}", "probe:no_side_effect"],
        )

    def _should_use_sql_brain(
        self,
        resource_action: object,
        contract: CompiledExecutionContract,
    ) -> bool:
        """
        判断当前 probe 是否应走 SQL Brain 技术探测。
        """

        if self.sql_brain_gateway is None:
            return False
        if contract.metadata.get("adapter_kind") != ADAPTER_KIND_SQL:
            return False
        resource_metadata = parse_sql_resource_metadata(
            contract.metadata.get("resource_metadata")
        )
        return bool(
            contract.params.get("sql_brain_enabled")
            or resource_metadata.sql_brain_enabled
            or contract.params.get("_system_sql_brain")
        )

    async def _probe_with_sql_brain(
        self,
        contract: CompiledExecutionContract,
    ) -> RuntimeResult:
        """
        使用 SQL Brain 做 SQL 的无副作用技术探测。

        这里仍然属于 Runtime 的稳定执行职责：
        - 不决定下一步业务动作
        - 只回答“这条已准备好的 SQL 从技术上能否安全进入正式执行”
        """

        resource_metadata_raw = contract.metadata.get("resource_metadata", {})
        if not isinstance(resource_metadata_raw, dict):
            resource_metadata_raw = {}
        resource_metadata = parse_sql_resource_metadata(resource_metadata_raw)
        system_sql_context = SqlPreparedContextPayload.from_mapping(
            contract.params.get("_system_sql_context")
        )
        tool_args = contract.params.get("tool_args", contract.params)
        if not isinstance(tool_args, dict):
            tool_args = {}
        resolved_source = self.sql_datasource_resolver.resolve(
            metadata=resource_metadata_raw,
            params={**contract.params, **tool_args},
        )
        transport_readiness_error = self._ensure_sql_probe_transport_ready(
            contract=contract,
            tool_args=tool_args,
            resource_metadata=resource_metadata,
            resolved_source=resolved_source,
        )
        if transport_readiness_error is not None:
            return transport_readiness_error

        sql = str(tool_args.get("query") or "").strip()
        if not sql:
            return RuntimeResult(
                run_id=contract.run_id,
                status=RUNTIME_STATUS_FAILED,
                summary="SQL probe 缺少待探测 SQL",
                facts={
                    "transport_status": "unknown",
                    "protocol_status": "unknown",
                    "business_status": "unknown",
                    "probe_supported": True,
                    "probe_only": True,
                    "sql_brain_used": True,
                },
                error="sql_probe_missing_query",
                evidence=["probe:sql_brain"],
            )

        context = SqlPlanContext(
            question=str(
                contract.params.get("question")
                or tool_args.get("question")
                or contract.action
                or ""
            ),
            resource_key=contract.resource_key,
            operation_key=contract.operation_key,
            connection_name=self._coalesce_str(
                tool_args.get("connection_name"),
                contract.params.get("connection_name"),
                resource_metadata.datasource.connection_name,
                resolved_source.get("connection_name"),
            ),
            db_url=self._coalesce_str(
                tool_args.get("db_url"),
                contract.params.get("db_url"),
                resource_metadata.datasource.db_url,
                resolved_source.get("db_url"),
            ),
            db_type=self._coalesce_str(
                contract.params.get("db_type"),
                resource_metadata.datasource.db_type,
                resolved_source.get("db_type"),
            ),
            read_only=bool(
                contract.params.get(
                    "read_only",
                    resolved_source.get("read_only", resource_metadata.datasource.read_only),
                )
            ),
            draft_sql=sql,
            schema_ddl=list(resource_metadata.sql_context.schema_ddl),
            example_sqls=list(system_sql_context.example_sqls),
            documentation_snippets=list(system_sql_context.documentation_snippets),
            metadata={**resource_metadata_raw, "resolved_datasource": resolved_source},
        )
        prepared_context = await self.sql_brain_gateway.prepare_context(context)
        probe_target = SqlProbeTarget(
            connection_name=prepared_context.connection_name,
            db_url=prepared_context.db_url,
            db_type=prepared_context.db_type,
            read_only=prepared_context.read_only,
            source="runtime_probe",
        )
        probe_result = self.sql_brain_gateway.probe_plan(
            sql=sql,
            context=prepared_context,
            target=probe_target,
        )
        return RuntimeResult(
            run_id=contract.run_id,
            status=RUNTIME_STATUS_SUCCESS if probe_result.ok else RUNTIME_STATUS_FAILED,
            summary=probe_result.summary,
            facts={
                "transport_status": "unknown",
                "protocol_status": "unknown",
                "business_status": "unknown",
                "probe_supported": True,
                "probe_only": True,
                "sql_brain_used": True,
                "probe_mode": probe_result.mode,
            },
            data={"sql_brain_probe": probe_result.model_dump(mode="json")},
            error=probe_result.error,
            evidence=["probe:sql_brain", f"tool:{contract.tool_name}"],
        )

    def _ensure_sql_probe_transport_ready(
        self,
        *,
        contract: CompiledExecutionContract,
        tool_args: dict[str, object],
        resource_metadata: object,
        resolved_source: dict[str, object],
    ) -> RuntimeResult | None:
        """
        校验 SQL probe 的正式执行承载路径是否可用。

        这里的边界非常明确：
        - probe 仍然不真实执行 SQL
        - 但也不能虚报“已可执行”
        - 因此要先按正式执行同一套承载路径判断：
          1. 如果未来会走 direct `db_url`，则不强依赖工具注册
          2. 如果未来必须走 `execute_sql_query` 之类工具，则 probe 前就要确认工具存在
        """

        if self._resolve_direct_db_url_for_probe(
            contract=contract,
            tool_args=tool_args,
            resource_metadata=resource_metadata,
            resolved_source=resolved_source,
        ):
            return None

        try:
            self.resource_catalog.get_tool(contract.tool_name)
        except KeyError as exc:
            return RuntimeResult(
                run_id=contract.run_id,
                status=RUNTIME_STATUS_FAILED,
                summary="SQL probe 检测到正式执行所需工具未注册，当前不能宣告可执行",
                facts={
                    "transport_status": "failed",
                    "protocol_status": "unknown",
                    "business_status": "unknown",
                    "probe_supported": True,
                    "probe_only": True,
                    "sql_brain_used": True,
                },
                error="probe_tool_unavailable",
                evidence=["probe:sql_brain", f"tool:{contract.tool_name}"],
                data={
                    "missing_tool": contract.tool_name,
                    "reason": str(exc),
                },
            )
        return None

    def _resolve_direct_db_url_for_probe(
        self,
        *,
        contract: CompiledExecutionContract,
        tool_args: dict[str, object],
        resource_metadata: object,
        resolved_source: dict[str, object],
    ) -> str | None:
        """
        以与 `SqlResourceAdapter` 正式执行一致的规则判断 probe 是否可直连数据库。

        只要显式存在 `connection_name`，正式执行就会优先走工具承载，
        因此这里也不能把 `db_url` 当成隐式兜底。
        """

        connection_name = self._coalesce_str(
            tool_args.get("connection_name"),
            contract.params.get("connection_name"),
            getattr(resource_metadata.datasource, "connection_name", None),
            resolved_source.get("connection_name"),
        )
        if connection_name:
            return None

        return self._coalesce_str(
            tool_args.get("db_url"),
            contract.params.get("db_url"),
            getattr(resource_metadata.datasource, "db_url", None),
            resolved_source.get("db_url"),
        )

    def _coalesce_str(self, *values: object) -> str | None:
        """
        返回第一个非空字符串。
        """

        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_string_list(self, value: object) -> list[str]:
        """
        把资源元数据中的字符串列表清洗成标准 list[str]。
        """

        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
