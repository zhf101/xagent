"""
智能造数顶层 `DataMakeReActPattern`（造数 ReAct 主控模式）。

这个模块对应你的 `Agent Control Plane`（Agent 控制平面），
目标是在尽量复用 xagent 原有 `Pattern + LLM + Context + Runner` 机制的前提下，
把造数领域的主循环落成一套真正可运行的最小闭环。

与通用 `ReActPattern`（推理执行模式）的关系：
- 复用点：
  - 仍然通过 `llm.chat()` 让模型输出结构化 JSON。
  - 仍然由 `AgentRunner` 调 `pattern.run()`。
  - 仍然通过 `AgentContext.state`（Agent 上下文状态）在多轮间传递数据。
- 核心差异：
  - 不再让主脑直接自由调用工具。
  - 主脑输出的是 `NextActionDecision`（下一动作决策），而不是 `tool_call`。
  - 执行路径必须经过 `ActionDispatcher -> Guard -> Runtime -> Resource`。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from json_repair import loads as repair_loads
from pydantic import ValidationError

from ...memory import MemoryStore
from ...model.chat.basic.base import BaseLLM
from ...tools.adapters.vibe import Tool
from ..context import AgentContext
from ..exceptions import LLMNotAvailableError, MaxIterationsError, PatternExecutionError
from ..trace import (
    TraceCategory,
    Tracer,
    trace_action_end,
    trace_ai_message,
    trace_error,
    trace_llm_call_start,
    trace_task_completion,
    trace_task_end,
    trace_task_start,
    trace_user_message,
)
from ..utils.compact import CompactConfig, CompactUtils
from ..utils.llm_utils import clean_messages
from ...datamake.application.dispatcher import ActionDispatcher
from ...datamake.application.interaction import InteractionBridge, UiResponseMapper
from ...datamake.application.orchestrator import DecisionBuilder, TerminationResolver
from ...datamake.application.supervision import (
    InvalidApprovalPayloadError,
    SupervisionBridge,
)
from ...datamake.contracts.constants import ACTION_KIND_EXECUTION
from ...datamake.contracts.decision import NextActionDecision
from ...datamake.contracts.interaction import ApprovalTicket, InteractionTicket
from ...datamake.contracts.observation import ObservationEnvelope
from ...datamake.guard.policy import ApprovalPolicy, RiskPolicy
from ...datamake.guard.readiness import ReadinessChecker
from ...datamake.guard.service import GuardService
from ...datamake.ledger.repository import LedgerRepository
from ...datamake.ledger.snapshots import SnapshotBuilder
from ...datamake.resources.catalog import ResourceCatalog
from ...datamake.resources.sql_datasource_resolver import SqlDatasourceResolver
from ...datamake.resources.http_adapter import HttpResourceAdapter
from ...datamake.resources.registry import ResourceActionDefinition
from ...datamake.resources.sql_brain_gateway import SqlBrainGateway
from ...datamake.resources.sql_adapter import SqlResourceAdapter
from ...datamake.resources.sql_schema_provider import SqlSchemaProvider
from ...datamake.runtime.compiler import ExecutionCompiler
from ...datamake.runtime.execution import ActionExecutor
from ...datamake.runtime.executor import RuntimeExecutor
from ...datamake.runtime.probe import ProbeExecutor
from ...datamake.runtime.recovery import RecoveryCoordinator
from ...datamake.runtime.resume_token import build_resume_token
from ...datamake.services.recall_service import RecallService
from ...datamake.services.approval_service import ApprovalService
from ...datamake.services.draft_service import DraftService
from ...datamake.services.models import FlowDraftState
from .base import AgentPattern

logger = logging.getLogger(__name__)
CONTEXT_KEY_FILE_INFO = "file_info"
CONTEXT_KEY_UPLOADED_FILES = "uploaded_files"


class DataMakeReActPattern(AgentPattern):
    """
    `DataMakeReActPattern`（造数 ReAct 主控模式）。

    所属分层：
    - 代码分层：`agent.pattern`
    - 需求分层：`Agent Control Plane`（Agent 控制平面）
    - 在你的设计里：顶层主脑 / 决策层

    当前实现策略：
    - 先把“单资源、受控动作、可回流”的最小闭环跑通。
    - 交互型等待态先兼容 `AgentRunner.need_user_input` 机制。
    - 执行型动作先只支持 `ResourceCatalog`（资源目录）里已注册的 SQL / HTTP 动作。
    - 复杂审批、DAG、多资源编排先不在第一阶段展开。
    """

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        max_iterations: int = 50,
        tracer: Optional[Tracer] = None,
        ledger_repository: Optional[LedgerRepository] = None,
        resource_catalog: Optional[ResourceCatalog] = None,
        compact_threshold: Optional[int] = None,
        enable_auto_compact: bool = True,
        compact_llm: Optional[BaseLLM] = None,
    ) -> None:
        self.llm = llm
        self.max_iterations = max_iterations
        self.tracer = tracer or Tracer()
        self.ledger_repository = ledger_repository or LedgerRepository()
        if ledger_repository is None:
            logger.warning(
                "DataMakeReActPattern: ledger_repository 未传入，使用内存模式。"
                " 进程重启后账本记录将丢失，生产环境请传入 PersistentLedgerRepository。"
            )
        self.resource_catalog = resource_catalog or ResourceCatalog()
        self.compact_llm = compact_llm or llm
        self.compact_config = CompactConfig(
            enabled=enable_auto_compact,
            threshold=compact_threshold or CompactConfig().threshold,
        )
        self._compact_stats = {"total_compacts": 0, "tokens_saved": 0}
        # 记录上一次 run() 的注册上下文签名。
        # 同一 task 虽然可能跨轮次恢复，但只要 tools / resource_actions 发生变化，
        # 注册表也必须重建，避免出现“上下文变了，注册表还沿用旧能力”的污染。
        self._last_run_registration_signature: Optional[str] = None

        # 下面这些组件一起构成第一阶段最小闭环。
        # 它们都尽量贴着你的五层架构来组织，而不是重新回退成“大 Pattern 全包”。
        self.snapshot_builder = SnapshotBuilder(self.ledger_repository)
        self.termination_resolver = TerminationResolver()
        self.approval_service = None
        self.draft_service = None
        if hasattr(self.ledger_repository, "session_factory"):
            self.approval_service = ApprovalService(
                self.ledger_repository.session_factory
            )
            self.draft_service = DraftService(self.ledger_repository.session_factory)
        self.interaction_bridge = InteractionBridge()
        self.supervision_bridge = SupervisionBridge(self.approval_service)
        self.ui_response_mapper = UiResponseMapper()

        self.sql_datasource_resolver = SqlDatasourceResolver()
        self.sql_schema_provider = SqlSchemaProvider(self.sql_datasource_resolver)
        self.sql_brain_gateway = SqlBrainGateway(
            llm=llm,
            schema_provider=self.sql_schema_provider,
            datasource_resolver=self.sql_datasource_resolver,
        )
        self.sql_adapter = SqlResourceAdapter(self.sql_brain_gateway)
        self.http_adapter = HttpResourceAdapter()
        self.execution_compiler = ExecutionCompiler(self.resource_catalog)
        self.probe_executor = ProbeExecutor(
            self.resource_catalog,
            self.sql_brain_gateway,
            self.sql_datasource_resolver,
        )
        self.action_executor = ActionExecutor(
            self.resource_catalog,
            self.sql_adapter,
            self.http_adapter,
        )
        self.runtime_executor = RuntimeExecutor(
            self.execution_compiler,
            self.probe_executor,
            self.action_executor,
        )
        self.recovery_coordinator = RecoveryCoordinator(self.ledger_repository)
        self.readiness_checker = ReadinessChecker(self.resource_catalog)
        self.risk_policy = RiskPolicy()
        self.approval_policy = ApprovalPolicy()
        self.guard_service = GuardService(
            resource_catalog=self.resource_catalog,
            runtime_executor=self.runtime_executor,
            readiness_checker=self.readiness_checker,
            risk_policy=self.risk_policy,
            approval_policy=self.approval_policy,
            sql_brain_gateway=self.sql_brain_gateway,
            sql_datasource_resolver=self.sql_datasource_resolver,
        )
        self.dispatcher = ActionDispatcher(
            interaction_bridge=self.interaction_bridge,
            supervision_bridge=self.supervision_bridge,
            guard_service=self.guard_service,
            termination_resolver=self.termination_resolver,
            ui_response_mapper=self.ui_response_mapper,
        )

    async def run(
        self,
        task: str,
        memory: MemoryStore,
        tools: list[Tool],
        context: Optional[AgentContext] = None,
    ) -> dict[str, Any]:
        """
        运行 `DataMakeReAct`（造数 ReAct）顶层控制循环。

        这里优先遵守两条设计原则：
        1. 顶层主脑只做业务决策，不直接自由调工具。
        2. 所有非终止结果都要统一回流为 `ObservationEnvelope`（观察结果外壳）。

        另外为了尽量兼容 xagent 当前运行方式，这里保留了：
        - `need_user_input` 返回结构，供 `AgentRunner` 继续驱动一轮人机交互。
        - `context.state` 作为多轮间共享状态容器。
        """

        context = context or AgentContext()
        task_id = context.task_id
        step_id, step_name = self._resolve_trace_step_context(task_id)

        await trace_user_message(
            self.tracer,
            task_id,
            task,
            data=self._build_user_trace_data(task, context, tools, step_id, step_name),
        )
        await trace_task_start(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "pattern": "DataMakeReAct",
                "task": task[:200],
                "max_iterations": self.max_iterations,
                "tools": [tool.metadata.name for tool in tools],
                "step_id": step_id,
                "step_name": step_name,
            },
        )

        try:
            self.resource_catalog.set_tools(tools)
            registration_signature = self._build_registration_signature(context, tools)
            # 【重要】资源动作注册表的清空策略：
            # - 同一 task 在 waiting_user / waiting_human 恢复时不应无脑清空注册表。
            # - 但只要 tools / resource_actions 变了，就必须重建注册表，
            #   否则 readiness / dispatch 会看到过期能力。
            if registration_signature != self._last_run_registration_signature:
                self.resource_catalog.clear_actions()
                self._register_resource_actions_from_context(context)
                self._last_run_registration_signature = registration_signature
            elif not self.resource_catalog.registry.list_all():
                self._register_resource_actions_from_context(context)
            recall_service = RecallService(memory)
            decision_builder = DecisionBuilder(
                self.snapshot_builder,
                recall_service,
                self.draft_service,
                self.resource_catalog,
            )

            # 连续失败计数器：同一类错误连续失败超过上限时，提前终止并返回友好提示，
            # 避免 403 / 号池耗尽等持续性错误无限重试耗尽全部迭代轮次。
            _consecutive_failures = 0
            _max_consecutive_failures = 5

            for _ in range(self.max_iterations):
                handled_pending, early_result = await self._consume_pending_replies(context)
                if early_result is not None:
                    await self._trace_run_result(task_id, early_result)
                    await trace_task_end(
                        self.tracer,
                        task_id,
                        TraceCategory.REACT,
                        data={
                            "status": early_result.get("status"),
                            "paused": True,
                            "step_id": step_id,
                            "step_name": step_name,
                        },
                    )
                    return early_result
                if handled_pending:
                    # 当前轮已经消费了外部回复，并写回 observation。
                    # 这里不直接返回，而是继续下一次决策，保持“结果回流后主脑重决策”的设计。
                    pass

                await self._persist_flow_draft_if_present(context)

                recovered_waiting = None
                if not handled_pending:
                    recovered_waiting = await self._recover_waiting_state(context)
                if recovered_waiting is not None:
                    await self._trace_run_result(task_id, recovered_waiting)
                    await trace_task_end(
                        self.tracer,
                        task_id,
                        TraceCategory.REACT,
                        data={
                            "status": recovered_waiting.get("status"),
                            "paused": True,
                            "step_id": step_id,
                            "step_name": step_name,
                            "recovered": True,
                        },
                    )
                    return recovered_waiting

                round_context = await decision_builder.build_round_context(task, context)
                round_id = int(round_context["ledger_snapshot"]["next_round_id"])
                try:
                    decision = await self._get_next_action_decision(
                        task,
                        round_context,
                        context,
                        task_id=task_id,
                        step_id=step_id,
                        round_id=round_id,
                    )
                except LLMNotAvailableError:
                    raise
                except Exception as exc:
                    _consecutive_failures += 1
                    logger.warning(
                        f"Round {round_id} 决策生成失败 "
                        f"({_consecutive_failures}/{_max_consecutive_failures}): {exc}"
                    )
                    await trace_error(
                        self.tracer,
                        task_id,
                        step_id,
                        error_type=type(exc).__name__,
                        error_message=f"Round {round_id} 决策失败: {str(exc)}",
                        data={
                            "round_id": round_id,
                            "retryable": _consecutive_failures < _max_consecutive_failures,
                            "attempt": _consecutive_failures,
                        },
                    )
                    if _consecutive_failures >= _max_consecutive_failures:
                        # 连续失败达上限，返回友好提示让用户稍后重试
                        error_result = {
                            "success": False,
                            "status": "error",
                            "need_user_input": True,
                            "question": (
                                f"模型服务连续 {_consecutive_failures} 次调用失败，"
                                f"最近错误：{str(exc)[:200]}。\n"
                                "请稍后重试，或联系管理员检查模型服务状态。"
                            ),
                            "field": "datamake_retry_confirm",
                            "error_type": type(exc).__name__,
                        }
                        await self._trace_run_result(task_id, error_result)
                        await trace_task_end(
                            self.tracer,
                            task_id,
                            TraceCategory.REACT,
                            data={
                                "status": "error",
                                "consecutive_failures": _consecutive_failures,
                                "step_id": step_id,
                                "step_name": step_name,
                            },
                        )
                        return error_result
                    await asyncio.sleep(2)
                    continue

                # 决策成功，重置连续失败计数
                _consecutive_failures = 0

                # 【重要】_hydrate_internal_decision_state 必须在 append_decision 之前调用。
                # 它负责把运行期系统内部状态（如 _system_approval_grants）注入 decision.params，
                # 这些字段需要一并持久化到账本，供后续审批审计和回放使用。
                # 如果先调 append_decision 再注入，账本记录就永远缺少这些字段，
                # 重放时会无法还原授权状态，导致审批逻辑误判。
                self._hydrate_internal_decision_state(decision, context)
                await self._trace_decision_output(task_id, decision, round_id)
                await self.ledger_repository.append_decision(
                    task_id=context.task_id,
                    round_id=round_id,
                    decision=decision,
                )

                try:
                    dispatch_outcome = await self.dispatcher.dispatch(
                        task_id=context.task_id,
                        session_id=context.session_id,
                        round_id=round_id,
                        decision=decision,
                    )
                except Exception as exc:
                    _consecutive_failures += 1
                    logger.warning(
                        f"Round {round_id} 动作分发失败 "
                        f"({_consecutive_failures}/{_max_consecutive_failures}): {exc}"
                    )
                    await trace_error(
                        self.tracer,
                        task_id,
                        step_id,
                        error_type=type(exc).__name__,
                        error_message=f"Round {round_id} 分发失败: {str(exc)}",
                        data={
                            "round_id": round_id,
                            "action": decision.action,
                            "retryable": _consecutive_failures < _max_consecutive_failures,
                            "attempt": _consecutive_failures,
                        },
                    )
                    if _consecutive_failures >= _max_consecutive_failures:
                        error_result = {
                            "success": False,
                            "status": "error",
                            "need_user_input": True,
                            "question": (
                                f"动作执行连续 {_consecutive_failures} 次失败，"
                                f"最近错误：{str(exc)[:200]}。\n"
                                "请稍后重试，或联系管理员检查服务状态。"
                            ),
                            "field": "datamake_retry_confirm",
                            "error_type": type(exc).__name__,
                        }
                        await self._trace_run_result(task_id, error_result)
                        await trace_task_end(
                            self.tracer,
                            task_id,
                            TraceCategory.REACT,
                            data={
                                "status": "error",
                                "consecutive_failures": _consecutive_failures,
                                "step_id": step_id,
                                "step_name": step_name,
                            },
                        )
                        return error_result
                    await asyncio.sleep(2)
                    continue

                if dispatch_outcome.kind == "final":
                    payload = dispatch_outcome.payload
                    payload.setdefault("iterations", round_id)
                    await self._trace_run_result(task_id, payload)
                    await trace_task_completion(
                        self.tracer,
                        task_id,
                        result=payload.get("output") or payload.get("final_message") or payload,
                        success=bool(payload.get("success", False)),
                    )
                    await trace_task_end(
                        self.tracer,
                        task_id,
                        TraceCategory.REACT,
                        data={
                            "status": payload.get("status"),
                            "iterations": round_id,
                            "success": payload.get("success"),
                            "step_id": step_id,
                            "step_name": step_name,
                        },
                    )
                    return payload

                if dispatch_outcome.kind == "observation":
                    observation = dispatch_outcome.payload["observation"]
                    await self.ledger_repository.append_observation(
                        task_id=context.task_id,
                        round_id=round_id,
                        observation=observation,
                    )
                    continue

                if dispatch_outcome.kind == "waiting_user":
                    ticket: InteractionTicket = dispatch_outcome.payload["ticket"]
                    pause_observation: ObservationEnvelope = dispatch_outcome.payload[
                        "pause_observation"
                    ]
                    await self.ledger_repository.append_ticket(
                        task_id=context.task_id,
                        round_id=round_id,
                        ticket=ticket,
                    )
                    await self.ledger_repository.append_observation(
                        task_id=context.task_id,
                        round_id=round_id,
                        observation=pause_observation,
                    )
                    result = {
                        "success": True,
                        "status": "waiting_user",
                        "need_user_input": True,
                        "question": dispatch_outcome.payload["question"],
                        "field": dispatch_outcome.payload["field"],
                        "chat_response": dispatch_outcome.payload["chat_payload"],
                        "ticket_id": ticket.ticket_id,
                    }
                    await self._trace_run_result(task_id, result)
                    await trace_task_end(
                        self.tracer,
                        task_id,
                        TraceCategory.REACT,
                        data={
                            "status": result["status"],
                            "paused": True,
                            "step_id": step_id,
                            "step_name": step_name,
                        },
                    )
                    return result

                if dispatch_outcome.kind == "waiting_human":
                    ticket = dispatch_outcome.payload["ticket"]
                    pause_observation = dispatch_outcome.payload["pause_observation"]
                    await self.ledger_repository.append_ticket(
                        task_id=context.task_id,
                        round_id=round_id,
                        ticket=ticket,
                    )
                    await self.ledger_repository.append_observation(
                        task_id=context.task_id,
                        round_id=round_id,
                        observation=pause_observation,
                    )
                    result = {
                        "success": True,
                        "status": "waiting_human",
                        "need_user_input": True,
                        "question": dispatch_outcome.payload["question"],
                        "field": dispatch_outcome.payload["field"],
                        "approval_id": ticket.approval_id,
                    }
                    await self._trace_run_result(task_id, result)
                    await trace_task_end(
                        self.tracer,
                        task_id,
                        TraceCategory.REACT,
                        data={
                            "status": result["status"],
                            "paused": True,
                            "step_id": step_id,
                            "step_name": step_name,
                        },
                    )
                    return result

            await trace_error(
                self.tracer,
                task_id,
                step_id,
                error_type="MaxIterationsError",
                error_message=f"造数智能体运行已超过最大迭代次数 {self.max_iterations}",
                data={
                    "pattern": "DataMakeReAct",
                    "task": task[:200],
                    "max_iterations": self.max_iterations,
                },
            )
            raise MaxIterationsError(
                pattern_name="DataMakeReAct",
                max_iterations=self.max_iterations,
                final_state="未在最大轮次内结束",
                context={
                    "task": task[:200],
                    "_already_traced": True,
                },
            )
        except (LLMNotAvailableError, MaxIterationsError, PatternExecutionError) as exc:
            await self._trace_pattern_failure(task_id, step_id, step_name, task, exc)
            raise
        except Exception as exc:
            wrapped = PatternExecutionError(
                pattern_name="DataMakeReAct",
                message=str(exc),
                context={"task": task[:200]},
                cause=exc,
            )
            await self._trace_pattern_failure(task_id, step_id, step_name, task, wrapped)
            raise wrapped from exc

    async def _consume_pending_replies(
        self,
        context: AgentContext,
    ) -> tuple[bool, dict[str, Any] | None]:
        """
        先处理可能已经存在于 `context.state` 的外部回复。

        这是当前实现与 xagent 原有 `AgentRunner.need_user_input` 机制的关键衔接点：
        - 上一轮 pattern 返回 `need_user_input`
        - Runner 把用户输入写到 `context.state[field]`
        - 下一次再次调用 `run()`
        - 这里读取该字段、回收 observation、继续重决策
        """

        interaction_ticket = await self.ledger_repository.load_pending_interaction(
            context.task_id
        )
        if interaction_ticket is not None:
            reply = context.state.get(interaction_ticket.response_field)
            if reply not in (None, ""):
                observation = await self.interaction_bridge.consume_reply(
                    interaction_ticket, reply
                )
                await self.ledger_repository.resolve_interaction_ticket(
                    context.task_id, interaction_ticket
                )
                await self.ledger_repository.append_observation(
                    task_id=context.task_id,
                    round_id=interaction_ticket.round_id,
                    observation=observation,
                )
                context.state.pop(interaction_ticket.response_field, None)
                return True, None

        approval_ticket = await self.ledger_repository.load_pending_approval(context.task_id)
        if approval_ticket is not None:
            reply = context.state.get(approval_ticket.response_field)
            if reply not in (None, ""):
                try:
                    observation = await self.supervision_bridge.consume_decision(
                        approval_ticket, reply
                    )
                except InvalidApprovalPayloadError as exc:
                    context.state.pop(approval_ticket.response_field, None)
                    return (
                        False,
                        {
                            "success": True,
                            "status": "waiting_human",
                            "need_user_input": True,
                            "question": (
                                f"审批输入格式错误：{exc}\n"
                                f"{self.supervision_bridge.build_waiting_question(approval_ticket)}"
                            ),
                            "field": approval_ticket.response_field,
                            "approval_id": approval_ticket.approval_id,
                        },
                    )
                await self.ledger_repository.resolve_approval_ticket(
                    context.task_id, approval_ticket
                )
                await self.ledger_repository.append_observation(
                    task_id=context.task_id,
                    round_id=approval_ticket.round_id,
                    observation=observation,
                )
                context.state.pop(approval_ticket.response_field, None)
                approval_key = approval_ticket.approval_key
                if observation.payload.get("approved"):
                    continuation_decision = approval_ticket.original_execution_decision
                    if (
                        not approval_key
                        and isinstance(continuation_decision, dict)
                        and continuation_decision.get("action_kind") == ACTION_KIND_EXECUTION
                    ):
                        approval_key = self.guard_service.build_approval_key(
                            NextActionDecision.model_validate(continuation_decision)
                        )

                    granted_keys = context.state.setdefault(
                        "datamake_approval_grants", []
                    )
                    if approval_key and approval_key not in granted_keys:
                        granted_keys.append(approval_key)

                    if isinstance(continuation_decision, dict):
                        injected_decision = dict(continuation_decision)
                        injected_decision.pop("decision_id", None)
                        injected_params = dict(injected_decision.get("params", {}))
                        if approval_key:
                            injected_params["approval_key"] = approval_key
                        injected_decision["params"] = injected_params
                        context.state["datamake_next_decision"] = injected_decision
                return True, None

        return False, None

    async def _get_next_action_decision(
        self,
        task: str,
        round_context: dict[str, Any],
        context: AgentContext,
        *,
        task_id: str,
        step_id: str,
        round_id: int,
    ) -> NextActionDecision:
        """
        获取当前轮 `NextActionDecision`（下一动作决策）。

        当前实现支持三种来源，按优先级依次为：
        1. `context.state["datamake_mock_decisions"]`
           方便测试与 smoke 验证，不依赖真实 LLM。
        2. `context.state["datamake_next_decision"]`
           方便单步人工注入一条决策。
        3. 真实 `llm.chat()`
           走结构化 JSON 输出。
        """

        injected_decision = context.state.pop("datamake_next_decision", None)
        if injected_decision is not None:
            return self._parse_decision_payload(injected_decision)

        mock_decisions = context.state.get("datamake_mock_decisions")
        if isinstance(mock_decisions, list) and mock_decisions:
            decision_payload = mock_decisions.pop(0)
            return self._parse_decision_payload(decision_payload)

        if self.llm is None:
            raise LLMNotAvailableError(
                "DataMakeReActPattern 未配置 LLM，无法生成下一动作决策。",
                context={
                    "pattern": "DataMakeReAct",
                    "task": task[:200],
                    "round_id": round_id,
                },
            )

        messages = self._build_llm_messages(task, round_context)
        messages = await self._check_and_compact_context(messages)
        await trace_llm_call_start(
            self.tracer,
            task_id,
            step_id,
            data={
                "pattern": "DataMakeReAct",
                "round_id": round_id,
                "model_name": getattr(self.llm, "model_name", "unknown"),
            },
        )
        response = await self.llm.chat(
            messages=clean_messages(messages),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        await trace_action_end(
            self.tracer,
            task_id,
            step_id,
            TraceCategory.LLM,
            data={
                "pattern": "DataMakeReAct",
                "round_id": round_id,
                "response_preview": self._extract_content(response)[:500],
            },
        )

        return self._parse_decision_payload(response)

    async def _recover_waiting_state(
        self,
        context: AgentContext,
    ) -> dict[str, Any] | None:
        """
        当任务已有持久化 pending 状态但当前轮没有新输入时，重建等待态返回。

        这里做的是技术态恢复，不替 Agent 选择新的业务动作。
        """

        recovered = await self.recovery_coordinator.resume(
            build_resume_token(
                task_id=context.task_id,
                reason="recover_waiting_state",
            )
        )

        if recovered["kind"] == "waiting_user":
            ticket: InteractionTicket = recovered["ticket"]
            return {
                "success": True,
                "status": "waiting_user",
                "need_user_input": True,
                "question": "\n".join(ticket.questions),
                "field": ticket.response_field,
                "chat_response": self.ui_response_mapper.to_chat_payload(ticket),
                "ticket_id": ticket.ticket_id,
                "resume_token": build_resume_token(
                    task_id=context.task_id,
                    round_id=ticket.round_id,
                    reason="pending_interaction",
                ),
            }

        if recovered["kind"] == "waiting_human":
            ticket: ApprovalTicket = recovered["ticket"]
            return {
                "success": True,
                "status": "waiting_human",
                "need_user_input": True,
                "question": self.supervision_bridge.build_waiting_question(ticket),
                "field": ticket.response_field,
                "approval_id": ticket.approval_id,
                "resume_token": build_resume_token(
                    task_id=context.task_id,
                    round_id=ticket.round_id,
                    reason="pending_approval",
                ),
            }

        return None

    def _build_llm_messages(
        self,
        task: str,
        round_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        构建提供给 LLM 的当前轮消息。

        这里尽量保持和 xagent 现有 `llm.chat()` 调用方式一致：
        - 用 `system + user` 两段消息
        - 强制要求返回 JSON 对象
        """

        base_system_prompt = (
            "你是智能造数平台的顶层业务决策 Agent。\n"
            "你必须基于当前上下文输出严格 JSON，结构符合 NextActionDecision。\n"
            "你不能直接调用工具，也不能假设 Guard/Runtime 会替你做业务判断。\n"
            "\n"
            "## 决策优先级\n"
            "1. 若 flow_draft.open_questions 非空，或召回命中不确定，优先 interaction_action 补全信息。\n"
            "2. 若 flow_draft 已有 confirmed_params 且 available_resources 已知，可直接 execution_action。\n"
            "3. 若动作 risk_level=high/critical 或 requires_approval=true，必须 supervision_action。\n"
            "4. 若任务目标已完成或无法继续，输出 terminate。\n"
            "5. 若当前没有 available_resources，且 recall_results 也为空，默认输出 interaction_action，"
            "向用户追问你需要的历史范围/业务域/筛选条件；不要输出空 action。\n"
            "\n"
            "## 输出完整性约束\n"
            "- 只要 decision_mode=action，action_kind 和 action 都必须填写，绝不能输出 null。\n"
            "- 若选择 interaction_action，params.questions 至少提供一个明确问题。\n"
            "- 若选择 terminate，final_status 和 final_message 必须填写。\n"
            "\n"
            "## execution_action 使用约束\n"
            "- params.resource_key 和 params.operation_key 必须来自 available_resources，不得凭空编造。\n"
            "- params.tool_args 只能包含该资源动作 result_contract 中声明的字段。\n"
            "- 若你决定采用某个资源的 sql_context_hints，必须显式写入 params.sql_context。\n"
            "- 若你采用了哪些 sql_context source，也必须显式写入 params.sql_context_sources。\n"
            "- params.sql_context 只是提供给 SQL Brain 的补充材料，不等于系统确认事实。\n"
            "\n"
            "## recall_results 使用约束\n"
            "- recall_results 是辅助参考，不是业务事实。命中相似历史不代表当前场景完全一致。\n"
            "- 若 recall_results 与当前 flow_draft 有冲突，以 flow_draft.confirmed_params 为准。\n"
            "\n"
            "## FILE REFERENCES\n"
            "- 你可能会看到形如 [filename](file://fileId) 的文件引用。\n"
            "- 其中真正可用于读取文件的标识是 fileId，而不是 filename。\n"
            "- uploaded_files / file_info 中的内容只是文件上下文，不代表你可以自由猜测文件内容。\n"
        )

        if round_context.get("system_prompt"):
            system_prompt = f"{round_context['system_prompt']}\n\n{base_system_prompt}"
        else:
            system_prompt = base_system_prompt

        # 从 round_context 中抽取关键摘要，避免把整个 context_state 全量喂给 LLM
        flow_draft = round_context.get("flow_draft") or {}
        available_resources = round_context.get("available_resources") or []
        recall_results = round_context.get("recall_results") or []
        ledger_snapshot = round_context.get("ledger_snapshot") or {}

        user_prompt = {
            "task": task,
            "flow_draft": flow_draft,
            "available_resources": available_resources,
            "recall_results": recall_results,
            "ledger_summary": {
                "next_round_id": ledger_snapshot.get("next_round_id"),
                "latest_decision": ledger_snapshot.get("latest_decision"),
                "latest_observation": ledger_snapshot.get("latest_observation"),
                "pending_interaction": ledger_snapshot.get("pending_interaction"),
                "pending_approval": ledger_snapshot.get("pending_approval"),
            },
            CONTEXT_KEY_FILE_INFO: round_context.get(CONTEXT_KEY_FILE_INFO),
            CONTEXT_KEY_UPLOADED_FILES: round_context.get(CONTEXT_KEY_UPLOADED_FILES),
            "response_contract": {
                "decision_mode": "action|terminate",
                "action_kind": "decision_mode=action 时必填：interaction_action|supervision_action|execution_action",
                "action": "decision_mode=action 时必填：string",
                "reasoning": "string（解释为什么现在选这个动作）",
                "goal_delta": "string（本轮推进了目标的哪一步）",
                "params": {
                    "（execution_action 时）resource_key": "来自 available_resources",
                    "（execution_action 时）operation_key": "来自 available_resources",
                    "（execution_action 时）tool_args": "{}",
                    "（interaction_action 时）questions": ["至少一个明确问题"],
                    "（execution_action 可选）sql_context": {
                        "schema_ddl": [],
                        "example_sqls": [],
                        "documentation_snippets": [],
                    },
                    "（execution_action 可选）sql_context_sources": [
                        {
                            "source_type": "memory_recall",
                            "source_id": "string|null",
                            "match_reason": "string",
                            "summary": "string|null",
                        }
                    ],
                },
                "risk_level": "low|medium|high|critical",
                "requires_approval": False,
                "user_visible": {
                    "title": "string",
                    "summary": "string",
                    "details": [],
                    "questions": [],
                },
                "final_status": "completed|failed|cancelled（terminate 时填写）",
                "final_message": "string（terminate 时填写）",
            },
        }

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ]

    def _parse_decision_payload(self, payload: Any) -> NextActionDecision:
        """
        将外部 payload 解析为 `NextActionDecision`。

        这里显式兼容：
        - pydantic model
        - dict
        - llm.chat() 返回的 json 字符串
        """

        if isinstance(payload, NextActionDecision):
            return payload

        if isinstance(payload, dict):
            return NextActionDecision.model_validate(payload)

        if isinstance(payload, str):
            try:
                parsed_payload = repair_loads(payload, logging=False)
                return NextActionDecision.model_validate(parsed_payload)
            except ValidationError:
                raise
            except Exception as exc:
                logger.error("解析 NextActionDecision JSON 失败: %s", exc)
                raise ValueError(f"无法解析 NextActionDecision JSON: {exc}") from exc

        if isinstance(payload, list):
            raise ValueError("NextActionDecision 不能是 list，必须是 JSON object")

        if hasattr(payload, "get"):
            return NextActionDecision.model_validate(payload)

        raise TypeError(f"不支持的决策 payload 类型: {type(payload)}")

    def _hydrate_internal_decision_state(
        self,
        decision: NextActionDecision,
        context: AgentContext,
    ) -> None:
        """
        把运行期内部状态注入当前决策对象。

        这些字段属于系统内部事实，不属于 LLM / 外部输入可声明的业务决策内容，
        因此只在 dispatch 前临时注入，不写回决策账本。
        """

        if decision.action_kind != ACTION_KIND_EXECUTION:
            return

        granted_keys = context.state.get("datamake_approval_grants", [])
        if not isinstance(granted_keys, list):
            granted_keys = []
        decision.params["_system_approval_grants"] = list(granted_keys)

    def _register_resource_actions_from_context(self, context: AgentContext) -> None:
        """
        从 `context.state` 注册第一阶段可用的资源动作。

        这样做的好处是：
        - 不强依赖数据库配置中心
        - 先让最小闭环可以用内存配置跑通
        - 未来再替换成正式注册中心读取逻辑时，Pattern 主循环不用大改
        """

        resource_actions = context.state.get("datamake_resource_actions", [])
        if not isinstance(resource_actions, list):
            return

        for item in resource_actions:
            if not isinstance(item, dict):
                continue
            try:
                definition = ResourceActionDefinition(**item)
                if not self.resource_catalog.has_action(
                    definition.resource_key, definition.operation_key
                ):
                    self.resource_catalog.register_action(definition)
            except Exception as exc:
                logger.warning("注册 datamake_resource_actions 项失败: %s", exc)

    def _build_registration_signature(
        self,
        context: AgentContext,
        tools: list[Tool],
    ) -> str:
        """
        生成当前注册上下文签名。

        这个签名只用于判断“是否要重建资源动作注册表”，
        不参与任何业务决策。
        """

        tool_names = sorted(tool.metadata.name for tool in tools)
        resource_actions = context.state.get("datamake_resource_actions", [])
        if not isinstance(resource_actions, list):
            resource_actions = []
        return json.dumps(
            {
                "task_id": context.task_id,
                "tool_names": tool_names,
                "resource_actions": resource_actions,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    async def _persist_flow_draft_if_present(self, context: AgentContext) -> None:
        """
        若当前上下文已携带 flow_draft，则把它持久化为工作记忆视图。

        这里只做“把已有草稿写入 Memory/Ledger”，不推导、不补齐新的业务状态。
        """

        if self.draft_service is None:
            return

        state_draft = context.state.get("flow_draft")
        if not isinstance(state_draft, dict):
            return

        persisted_draft = await self.draft_service.load(context.task_id)
        draft_payload = (
            persisted_draft.model_dump(mode="json")
            if persisted_draft is not None
            else {}
        )
        draft_payload.update(state_draft)
        draft_payload.setdefault("task_id", context.task_id)
        draft_payload.setdefault(
            "version",
            persisted_draft.version if persisted_draft is not None else 1,
        )
        await self.draft_service.save(FlowDraftState.model_validate(draft_payload))

    def _estimate_message_tokens(self, messages: list[dict[str, str]]) -> int:
        """
        估算当前消息的 token 数。
        """

        return CompactUtils.estimate_tokens(messages)

    async def _check_and_compact_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        在调用 LLM 前检查上下文长度，必要时执行压缩。
        """

        if not self.compact_config.enabled:
            return messages

        estimated_tokens = self._estimate_message_tokens(messages)
        if estimated_tokens <= self.compact_config.threshold:
            return messages

        return await self._compact_datamake_context(messages)

    async def _compact_datamake_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        对 datamake 当前轮消息做压缩。

        当前策略尽量复用 xagent 通用压缩能力：
        - 有 compact_llm 时，优先让模型总结旧上下文
        - 没有 compact_llm 时，退化为保留 system + 最近 user 消息
        """

        original_tokens = self._estimate_message_tokens(messages)
        if self.compact_llm is None:
            return self._fallback_truncate_messages(messages, original_tokens)

        compact_prompt = [
            {
                "role": "system",
                "content": (
                    "你在压缩智能造数 ReAct 上下文。"
                    "请保留：当前任务、最近 observation、待处理审批/交互、资源动作限制、文件上下文。"
                    "请删除：过时细节、冗余字段、重复描述。"
                    "返回仍然是两段消息格式：SYSTEM: ...\\nUSER: ..."
                ),
            },
            {
                "role": "user",
                "content": CompactUtils.format_messages_for_compact(messages),
            },
        ]

        try:
            response = await self.compact_llm.chat(messages=clean_messages(compact_prompt))
            content = self._extract_content(response)
            compacted_messages = self._parse_compact_response(content)
            if not compacted_messages:
                return self._fallback_truncate_messages(messages, original_tokens)

            final_tokens = self._estimate_message_tokens(compacted_messages)
            self._compact_stats["total_compacts"] += 1
            self._compact_stats["tokens_saved"] += max(original_tokens - final_tokens, 0)
            return compacted_messages
        except Exception as exc:
            logger.warning("DataMakeReActPattern 上下文压缩失败，改用截断兜底: %s", exc)
            return self._fallback_truncate_messages(messages, original_tokens)

    def _fallback_truncate_messages(
        self,
        messages: list[dict[str, str]],
        original_tokens: int,
    ) -> list[dict[str, str]]:
        """
        压缩失败时的兜底截断逻辑。
        """

        system_msg = next((msg for msg in messages if msg.get("role") == "system"), None)
        recent_user_msg = next((msg for msg in reversed(messages) if msg.get("role") == "user"), None)
        compacted_messages = [msg for msg in [system_msg, recent_user_msg] if msg is not None]
        final_tokens = self._estimate_message_tokens(compacted_messages)
        self._compact_stats["total_compacts"] += 1
        self._compact_stats["tokens_saved"] += max(original_tokens - final_tokens, 0)
        return compacted_messages

    def _parse_compact_response(self, response: str) -> list[dict[str, str]]:
        """
        解析压缩模型返回的 `SYSTEM: ... / USER: ...` 文本。
        """

        messages: list[dict[str, str]] = []
        current_role: Optional[str] = None
        current_content: list[str] = []

        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("SYSTEM:", "USER:", "ASSISTANT:")):
                if current_role and current_content:
                    messages.append(
                        {
                            "role": current_role.lower(),
                            "content": "\n".join(current_content),
                        }
                    )
                parts = line.split(":", 1)
                current_role = parts[0]
                current_content = [parts[1].strip()] if len(parts) > 1 else []
            elif current_role:
                current_content.append(line)

        if current_role and current_content:
            messages.append(
                {
                    "role": current_role.lower(),
                    "content": "\n".join(current_content),
                }
            )

        return messages

    def _extract_content(self, response: Any) -> str:
        """
        从 xagent LLM 返回结果中提取文本内容。
        """

        if response is None:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "content" in response:
                return str(response["content"])
            return json.dumps(response, ensure_ascii=False, default=str)
        return str(response)

    def get_compact_stats(self) -> dict[str, Any]:
        """
        返回当前上下文压缩统计信息。
        """

        return {
            **self._compact_stats,
            "enabled": self.compact_config.enabled,
            "threshold": self.compact_config.threshold,
        }

    def _resolve_trace_step_context(self, task_id: str) -> tuple[str, str]:
        """
        为 datamake 当前运行构造稳定的 step 上下文。
        """

        step_id = getattr(self, "_current_step_id", None) or f"{task_id}_main"
        step_name = getattr(self, "_current_step_name", None) or "main"
        self._current_step_id = step_id
        self._current_step_name = step_name
        return step_id, step_name

    def _build_user_trace_data(
        self,
        task: str,
        context: AgentContext,
        tools: list[Tool],
        step_id: str,
        step_name: str,
    ) -> dict[str, Any]:
        """
        组装任务级用户输入 trace 数据。
        """

        return {
            "pattern": "DataMakeReAct",
            "task": task[:200],
            "tools": [tool.metadata.name for tool in tools],
            "step_id": step_id,
            "step_name": step_name,
            "file_info": context.state.get(CONTEXT_KEY_FILE_INFO),
            "uploaded_files": context.state.get(CONTEXT_KEY_UPLOADED_FILES),
        }

    async def _trace_decision_output(
        self,
        task_id: str,
        decision: NextActionDecision,
        round_id: int,
    ) -> None:
        """
        记录当前轮 AI 决策输出。
        """

        await trace_ai_message(
            self.tracer,
            task_id,
            message=json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
            data={
                "decision_mode": decision.decision_mode,
                "action_kind": decision.action_kind,
                "action": decision.action,
                "round_id": round_id,
            },
        )

    async def _trace_run_result(self, task_id: str, result: dict[str, Any]) -> None:
        """
        记录本次 run 返回给外部调用方的结果摘要。
        """

        message = None
        for key in ("output", "question", "final_message"):
            value = result.get(key)
            if value not in (None, ""):
                message = str(value)
                break
        if message is None:
            message = json.dumps(result, ensure_ascii=False, default=str)
        await trace_ai_message(
            self.tracer,
            task_id,
            message=message,
            data={
                "status": result.get("status"),
                "success": result.get("success"),
            },
        )

    async def _trace_pattern_failure(
        self,
        task_id: str,
        step_id: str,
        step_name: str,
        task: str,
        exc: Exception,
    ) -> None:
        """
        对统一异常边界做 trace 收口。
        """

        error_context = getattr(exc, "context", {}) if hasattr(exc, "context") else {}
        if not error_context.get("_already_traced"):
            await trace_error(
                self.tracer,
                task_id,
                step_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                data={
                    "pattern": "DataMakeReAct",
                    "task": task[:200],
                    "step_name": step_name,
                    "context": error_context,
                },
            )

        await trace_task_end(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "status": "failed",
                "success": False,
                "step_id": step_id,
                "step_name": step_name,
                "error_type": type(exc).__name__,
            },
        )
