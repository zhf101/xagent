"""
`GuardService`（护栏服务）入口模块。

这里的职责是给 execution_action 做护栏裁决：
- 是否允许进入 Runtime
- 是否必须先审批
- 是否应该走 probe 还是 execute

注意：
需要审批不等于 blocker。
审批要求属于“可继续，但必须先走 supervision 通道”的治理结论，
因此这里会把结果返回给 `ActionDispatcher`（动作分发器），
由上层去真正创建 `ApprovalTicket`（审批工单）。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from ..contracts.constants import (
    ADAPTER_KIND_SQL,
    ACTION_KIND_EXECUTION,
    EXECUTION_ACTION_COMPILE_FLOW_DRAFT,
    EXECUTION_ACTION_EXECUTE_COMPILED_DAG,
    EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION,
    EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION,
    EXECUTION_MODE_PROBE,
    GUARD_RESULT_KIND_APPROVAL_REQUIRED,
    GUARD_RESULT_KIND_OBSERVATION,
    OBSERVATION_STATUS_BLOCKED,
    OBSERVATION_TYPE_BLOCKER,
    ROUTE_RUNTIME_EXECUTE,
    ROUTE_RUNTIME_PROBE,
)
from ..contracts.decision import NextActionDecision
from ..contracts.guard import GuardVerdict, ReadinessSnapshot
from ..contracts.observation import ObservationActor, ObservationEnvelope
from ..resources.catalog import ResourceCatalog
from ..resources.registry import ResourceActionDefinition
from ..resources.sql_datasource_resolver import SqlDatasourceResolver
from ..resources.sql_brain_gateway import SqlBrainGateway
from ..resources.sql_resource_definition import (
    SqlContextMaterialSet,
    SqlContextHintSource,
    SqlPreparedContextPayload,
    parse_sql_resource_metadata,
)
from ..contracts.sql_plan import SqlPlanContext
from ..runtime.executor import RuntimeExecutor
from .policy import ApprovalPolicy, RiskPolicy
from .readiness import ReadinessChecker


class GuardEvaluationResult(BaseModel):
    """
    `GuardEvaluationResult`（护栏评估结果）。

    这里不是对外长期契约，而是 guard 与 dispatcher 之间的内部结构。
    它明确区分三类结果：
    - `observation`：已经形成 observation，可直接回流
    - `approval_required`：当前动作需要转入人工审批通道
    - `runtime`：当前动作已允许进入 Runtime
    """

    kind: str = Field(description="guard 评估结果类型。")
    payload: dict[str, object] = Field(default_factory=dict)


class GuardService:
    """
    `GuardService`（护栏服务）。
    """

    def __init__(
        self,
        resource_catalog: ResourceCatalog,
        runtime_executor: RuntimeExecutor,
        readiness_checker: ReadinessChecker,
        risk_policy: RiskPolicy,
        approval_policy: ApprovalPolicy,
        sql_brain_gateway: SqlBrainGateway | None = None,
        sql_datasource_resolver: SqlDatasourceResolver | None = None,
    ) -> None:
        self.resource_catalog = resource_catalog
        self.runtime_executor = runtime_executor
        self.readiness_checker = readiness_checker
        self.risk_policy = risk_policy
        self.approval_policy = approval_policy
        self.sql_brain_gateway = sql_brain_gateway
        self.sql_datasource_resolver = sql_datasource_resolver or SqlDatasourceResolver()

    async def evaluate(self, action: NextActionDecision) -> GuardEvaluationResult:
        """
        对执行动作进行护栏裁决。
        """

        readiness = await self.readiness_checker.check(action)
        if not readiness.resource_ready or not readiness.params_ready:
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_OBSERVATION,
                payload={
                    "observation": ObservationEnvelope(
                        observation_type=OBSERVATION_TYPE_BLOCKER,
                        action_kind=ACTION_KIND_EXECUTION,
                        action=action.action,
                        status=OBSERVATION_STATUS_BLOCKED,
                        actor=ObservationActor(type="system"),
                        result={"summary": "执行前置条件不满足，已被 Guard 阻断"},
                        error="资源未注册或参数不完整",
                        payload={
                            "resource_key": action.params.get("resource_key"),
                            "operation_key": action.params.get("operation_key"),
                            "readiness": readiness.model_dump(mode="json"),
                        },
                    )
                },
            )

        special_result = await self._evaluate_template_pipeline_action(
            action=action,
            readiness=readiness,
        )
        if special_result is not None:
            return special_result

        resource_action = self.resource_catalog.get_action(
            str(action.params["resource_key"]),
            str(action.params["operation_key"]),
        )
        if self._should_use_sql_brain(action, resource_action):
            sql_guard_result = await self._prepare_sql_action(action, resource_action)
            if sql_guard_result is not None:
                return sql_guard_result

        risk_level = self.risk_policy.evaluate_risk(action, resource_action)
        sql_brain_state = action.params.get("_system_sql_brain")
        sql_verification: dict[str, Any] | None = None
        if isinstance(sql_brain_state, dict):
            verification = sql_brain_state.get("verification")
            if isinstance(verification, dict):
                sql_verification = verification
                risk_level = self.risk_policy.merge_risk_levels(
                    risk_level,
                    str(verification.get("risk_level", "low")),
                )
        probe_requested = self._is_probe_requested(action)
        approval_required = self.approval_policy.requires_approval(action, resource_action)
        if (
            not approval_required
            and not probe_requested
            and self._should_require_sql_supervision(
                action=action,
                resource_action=resource_action,
                risk_level=risk_level,
                verification=sql_verification,
            )
        ):
            approval_required = True

        if probe_requested and not resource_action.supports_probe:
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_OBSERVATION,
                payload={
                    "observation": ObservationEnvelope(
                        observation_type=OBSERVATION_TYPE_BLOCKER,
                        action_kind=ACTION_KIND_EXECUTION,
                        action=action.action,
                        status=OBSERVATION_STATUS_BLOCKED,
                        actor=ObservationActor(type="system"),
                        result={"summary": "当前资源动作不支持 probe 探测执行"},
                        error="probe_not_supported",
                        payload={
                            "resource_key": action.params.get("resource_key"),
                            "operation_key": action.params.get("operation_key"),
                        },
                    )
                },
            )

        route = ROUTE_RUNTIME_PROBE if probe_requested else ROUTE_RUNTIME_EXECUTE

        verdict = GuardVerdict(
            allowed=True,
            normalized_action=action.action or "execute_registered_action",
            route=route,
            blockers=[],
            approval_required=approval_required,
            risk_level=risk_level,
            readiness_snapshot=readiness,
        )

        if approval_required:
            approval_key = self.build_approval_key(action)
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_APPROVAL_REQUIRED,
                payload={
                    "verdict": verdict,
                    "approval_key": approval_key,
                    "summary": "当前动作需要人工审批，已转入等待人工确认通道",
                },
            )

        observation = await self.runtime_executor.execute(action, verdict)
        return GuardEvaluationResult(
            kind=GUARD_RESULT_KIND_OBSERVATION,
            payload={"observation": observation},
        )

    async def _evaluate_template_pipeline_action(
        self,
        *,
        action: NextActionDecision,
        readiness: ReadinessSnapshot,
    ) -> GuardEvaluationResult | None:
        """
        处理模板沉淀链路的特殊 execution_action。

        这类动作不依赖 `resource_key/operation_key`，因此不能套用单资源 guard 规则。
        但它们仍然必须通过：
        - 最小参数前置条件
        - 风险 / 审批裁决
        - Runtime 执行回流
        """

        if action.action not in {
            EXECUTION_ACTION_COMPILE_FLOW_DRAFT,
            EXECUTION_ACTION_EXECUTE_COMPILED_DAG,
            EXECUTION_ACTION_PUBLISH_TEMPLATE_VERSION,
            EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION,
        }:
            return None

        risk_level = str(action.risk_level or "low").strip().lower() or "low"
        approval_required = bool(action.requires_approval)
        # 模板链路动作虽然不依赖具体 resource_action，
        # 但审批放行语义必须与普通 execution_action 保持一致：
        # 同一个 approval_key 一旦已经进入 `_system_approval_grants`，
        # 本轮 continuation 恢复时就应直接放行，而不是再次开新审批单。
        if self._has_approval_grant(action):
            approval_required = False
        verdict = GuardVerdict(
            allowed=True,
            normalized_action=action.action or "",
            route=ROUTE_RUNTIME_EXECUTE,
            blockers=[],
            approval_required=approval_required,
            risk_level=risk_level,
            readiness_snapshot=readiness,
        )
        if approval_required:
            approval_key = self.build_approval_key(action)
            return GuardEvaluationResult(
                kind=GUARD_RESULT_KIND_APPROVAL_REQUIRED,
                payload={
                    "verdict": verdict,
                    "approval_key": approval_key,
                    "summary": "当前模板链路动作需要人工审批，已转入等待人工确认通道",
                },
            )

        observation = await self.runtime_executor.execute(action, verdict)
        return GuardEvaluationResult(
            kind=GUARD_RESULT_KIND_OBSERVATION,
            payload={"observation": observation},
        )

    def _has_approval_grant(self, action: NextActionDecision) -> bool:
        """
        判断当前执行动作是否已经携带有效审批放行凭据。

        这个判断只表达“同一动作在同一审批键下已被人工明确放行”，
        不能推导新的业务动作，也不能替代风险评估本身。
        """

        approval_key = action.params.get("approval_key")
        approved_grants = action.params.get("_system_approval_grants", [])
        return (
            isinstance(approval_key, str)
            and isinstance(approved_grants, list)
            and approval_key in approved_grants
        )

    def _should_use_sql_brain(
        self,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
    ) -> bool:
        """
        判断当前 SQL 资源动作是否需要进入 SQL Brain 预处理。

        只有显式启用时才进入，避免把所有 SQL 资源都强制改成新链路。
        """

        if self.sql_brain_gateway is None:
            return False
        if resource_action.adapter_kind != ADAPTER_KIND_SQL:
            return False
        metadata = parse_sql_resource_metadata(resource_action.metadata)
        return bool(
            action.params.get("sql_brain_enabled")
            or metadata.sql_brain_enabled
        )

    async def _prepare_sql_action(
        self,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
    ) -> GuardEvaluationResult | None:
        """
        在 Guard 阶段完成 SQL 的技术预处理。

        这里做的是：
        - 形成 SQL 草案
        - 做静态校验
        - 必要时尝试修复
        - 把最终 SQL 与技术事实写回系统内部参数

        这里不做的是：
        - 不替 Agent 决定下一步业务动作
        - 不绕过审批
        - 不真实执行 SQL
        """

        context = self._build_sql_plan_context(action, resource_action)
        prepared_context = await self.sql_brain_gateway.prepare_context(context)
        plan = await self.sql_brain_gateway.generate_plan(prepared_context)
        if not plan.success or not plan.sql:
            return self._build_sql_blocker(
                action=action,
                error="sql_plan_unavailable",
                summary="SQL 规划失败，当前动作未进入执行",
                payload={
                    "sql_brain": {
                        "plan": plan.model_dump(mode="json"),
                    }
                },
            )

        verification = self.sql_brain_gateway.verify_plan(
            sql=plan.sql,
            context=prepared_context,
        )
        final_sql = plan.sql
        final_verification = verification
        repair_payload: dict[str, Any] | None = None

        if not verification.valid:
            repair = await self.sql_brain_gateway.repair_plan(
                sql=plan.sql,
                context=prepared_context,
                verification=verification,
            )
            repair_payload = repair.model_dump(mode="json")
            if repair.repaired_sql:
                repaired_verification = self.sql_brain_gateway.verify_plan(
                    sql=repair.repaired_sql,
                    context=prepared_context,
                )
                if repaired_verification.valid:
                    final_sql = repair.repaired_sql
                    final_verification = repaired_verification

        if not final_verification.valid:
            return self._build_sql_blocker(
                action=action,
                error="sql_verification_failed",
                summary="SQL 静态校验未通过，Guard 已阻断本次执行",
                payload={
                    "sql_brain": {
                        "plan": plan.model_dump(mode="json"),
                        "verification": verification.model_dump(mode="json"),
                        "repair": repair_payload,
                    }
                },
            )

        tool_args = action.params.get("tool_args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}
        tool_args["query"] = final_sql
        if context.connection_name and "connection_name" not in tool_args:
            tool_args["connection_name"] = context.connection_name
        if context.db_url and "db_url" not in tool_args:
            tool_args["db_url"] = context.db_url
        action.params["tool_args"] = tool_args
        action.params["_system_sql_brain"] = {
            "enabled": True,
            "plan": plan.model_dump(mode="json"),
            "verification": final_verification.model_dump(mode="json"),
            "repair": repair_payload,
            "final_sql": final_sql,
        }
        if context.metadata.get("resolved_datasource"):
            action.params["_system_sql_datasource"] = context.metadata.get(
                "resolved_datasource"
            )
        prepared_payload = SqlPreparedContextPayload.from_prepared_context(prepared_context)
        raw_sources = action.params.get("sql_context_sources", [])
        if isinstance(raw_sources, list):
            prepared_payload.context_sources = [
                SqlContextHintSource(
                    source_type=str(item.get("source_type") or "memory_recall"),
                    source_id=self._coalesce_str(item.get("source_id")),
                    match_reason=str(item.get("match_reason") or "generic_sql"),
                    summary=self._coalesce_str(item.get("summary")),
                )
                for item in raw_sources
                if isinstance(item, dict)
            ]
        action.params["_system_sql_context"] = prepared_payload.model_dump(mode="json")
        return None

    def _build_sql_plan_context(
        self,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
    ) -> SqlPlanContext:
        """
        从当前执行动作和资源定义构造 SQL Brain 所需上下文。
        """

        tool_args = action.params.get("tool_args", {})
        if not isinstance(tool_args, dict):
            tool_args = {}

        question = self._coalesce_str(
            action.params.get("question"),
            action.params.get("query_intent"),
            action.params.get("natural_language_query"),
            tool_args.get("question"),
            tool_args.get("prompt"),
            action.user_visible.summary,
            action.reasoning,
            action.action,
        ) or ""
        resource_metadata = dict(resource_action.metadata)
        parsed_metadata = parse_sql_resource_metadata(resource_metadata)
        action_sql_context = SqlContextMaterialSet.from_mapping(
            action.params.get("sql_context")
        )
        effective_sql_context = parsed_metadata.sql_context.merge(action_sql_context)
        resolved_source = self.sql_datasource_resolver.resolve(
            metadata=resource_metadata,
            params={**action.params, **tool_args},
        )

        return SqlPlanContext(
            question=question,
            resource_key=resource_action.resource_key,
            operation_key=resource_action.operation_key,
            connection_name=self._coalesce_str(
                tool_args.get("connection_name"),
                action.params.get("connection_name"),
                parsed_metadata.datasource.connection_name,
                resolved_source.get("connection_name"),
            ),
            db_url=self._coalesce_str(
                tool_args.get("db_url"),
                action.params.get("db_url"),
                parsed_metadata.datasource.db_url,
                resolved_source.get("db_url"),
            ),
            db_type=self._coalesce_str(
                action.params.get("db_type"),
                parsed_metadata.datasource.db_type,
                resolved_source.get("db_type"),
            ),
            read_only=bool(
                action.params.get(
                    "read_only",
                    resolved_source.get("read_only", parsed_metadata.datasource.read_only),
                )
            ),
            draft_sql=self._coalesce_str(
                tool_args.get("query"),
                action.params.get("draft_sql"),
                action.params.get("sql"),
            ),
            schema_ddl=list(effective_sql_context.schema_ddl),
            example_sqls=list(effective_sql_context.example_sqls),
            documentation_snippets=list(
                effective_sql_context.documentation_snippets
            ),
            metadata={
                **resource_metadata,
                "resolved_datasource": resolved_source,
                "user_id": action.params.get("_system_user_id")
                if action.params.get("_system_user_id") is not None
                else action.params.get("user_id"),
            },
        )

    def _should_require_sql_supervision(
        self,
        *,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
        risk_level: str,
        verification: dict[str, Any] | None,
    ) -> bool:
        """
        在 SQL 静态校验已经明确抬高风险后，决定是否自动进入 supervision。

        这里的边界是：
        - 不是“高风险就直接拒绝”
        - 而是“高风险 SQL 不能绕过人工确认直接正式执行”
        - 同时仍然尊重既有 approval grant 恢复链
        """

        if resource_action.adapter_kind != ADAPTER_KIND_SQL:
            return False
        if verification is None:
            return False

        normalized_risk = self.risk_policy.merge_risk_levels(risk_level)
        if normalized_risk not in {"high", "critical"}:
            return False

        approval_key = action.params.get("approval_key")
        approved_grants = action.params.get("_system_approval_grants", [])
        if (
            isinstance(approval_key, str)
            and isinstance(approved_grants, list)
            and approval_key in approved_grants
        ):
            return False
        return True

    def _build_sql_blocker(
        self,
        *,
        action: NextActionDecision,
        error: str,
        summary: str,
        payload: dict[str, Any],
    ) -> GuardEvaluationResult:
        """
        生成 SQL 技术预处理失败时的 blocker observation。
        """

        return GuardEvaluationResult(
            kind=GUARD_RESULT_KIND_OBSERVATION,
            payload={
                "observation": ObservationEnvelope(
                    observation_type=OBSERVATION_TYPE_BLOCKER,
                    action_kind=ACTION_KIND_EXECUTION,
                    action=action.action,
                    status=OBSERVATION_STATUS_BLOCKED,
                    actor=ObservationActor(type="system"),
                    result={"summary": summary},
                    error=error,
                    payload={
                        "resource_key": action.params.get("resource_key"),
                        "operation_key": action.params.get("operation_key"),
                        **payload,
                    },
                )
            },
        )

    def _coalesce_str(self, *values: Any) -> str | None:
        """
        返回第一个非空字符串。
        """

        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_string_list(self, value: Any) -> list[str]:
        """
        把资源元数据中的字符串列表清洗成 list[str]。
        """

        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _is_probe_requested(self, action: NextActionDecision) -> bool:
        """
        判断当前动作是否明确请求 probe。

        注意这里不能把 `supports_probe=True` 误解成“必须先走 probe”。
        `supports_probe` 只是能力声明，不是默认执行路线。
        """

        execution_mode = str(action.params.get("execution_mode", "")).lower()
        if execution_mode == EXECUTION_MODE_PROBE:
            return True
        if action.params.get("probe") is True:
            return True
        return action.action in {"probe_registered_action", "probe_step"}

    def build_approval_key(self, action: NextActionDecision) -> str:
        """
        生成审批授权键。

        这把键用于把“某个具体执行动作已经被人工放行”记录下来，
        避免同一个动作在审批通过后又再次被 Guard 误判为还需要审批。
        """

        def _stable(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _stable(v) for k, v in sorted(obj.items())}
            if isinstance(obj, list):
                return [_stable(i) for i in sorted(obj, key=lambda i: json.dumps(i, ensure_ascii=False, sort_keys=True))]
            return obj

        approval_payload = {
            "action": action.action,
            "resource_key": action.params.get("resource_key"),
            "operation_key": action.params.get("operation_key"),
            "template_draft_id": action.params.get("template_draft_id"),
            "template_version_id": action.params.get("template_version_id"),
            "tool_args": _stable(action.params.get("tool_args", {})),
        }
        return "v1:" + json.dumps(approval_payload, ensure_ascii=False, sort_keys=True)
