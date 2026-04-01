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

import json
import logging
from typing import Any, Optional

from ...memory import MemoryStore
from ...model.chat.basic.base import BaseLLM
from ...tools.adapters.vibe import Tool
from ..context import AgentContext
from ..exceptions import LLMNotAvailableError, MaxIterationsError, PatternExecutionError
from ..trace import (
    TraceCategory,
    Tracer,
)
from ..utils.compact import CompactConfig
from ...datamake.application.dispatcher import ActionDispatcher
from ...datamake.application.evidence_budget import EvidenceBudgetManager
from ...datamake.application.flow_draft_sync import FlowDraftSyncCoordinator
from ...datamake.application.interaction import InteractionBridge, UiResponseMapper
from ...datamake.application.agent_capability_adapter import (
    DataMakeAgentCapabilityAdapter,
)
from ...datamake.application.decision_provider import DataMakeDecisionProvider
from ...datamake.application.decision_runner import (
    DataMakeDecisionRunner,
    DataMakeRunInput,
    DataMakeRunnerHooks,
    DataMakeRunnerPorts,
)
from ...datamake.application.pending_reply_coordinator import PendingReplyCoordinator
from ...datamake.application.orchestrator import DecisionBuilder, TerminationResolver
from ...datamake.application.pattern_hooks import PatternHookAdapter
from ...datamake.application.prompt_builder import DataMakePromptBuilder
from ...datamake.application.resource_registration import (
    DataMakeResourceRegistrationCoordinator,
)
from ...datamake.application.supervision import (
    SupervisionBridge,
)
from ...datamake.contracts.constants import (
    ACTION_KIND_EXECUTION,
    EXECUTION_ACTION_COMPILE_FLOW_DRAFT,
    EXECUTION_ACTION_EXECUTE_COMPILED_DAG,
    EXECUTION_ACTION_EXECUTE_REGISTERED_ACTION,
    EXECUTION_ACTION_EXECUTE_TEMPLATE_VERSION,
    EXECUTION_ACTION_PROBE_REGISTERED_ACTION,
)
from ...datamake.contracts.decision import NextActionDecision
from ...datamake.guard.policy import ApprovalPolicy, RiskPolicy
from ...datamake.guard.readiness import ReadinessChecker
from ...datamake.guard.service import GuardService
from ...datamake.ledger.repository import LedgerRepository
from ...datamake.ledger.snapshots import SnapshotBuilder
from ...datamake.resources.catalog import ResourceCatalog
from ...datamake.resources.sql_datasource_resolver import SqlDatasourceResolver
from ...datamake.resources.http_adapter import HttpResourceAdapter
from ...datamake.resources.sql_brain_gateway import SqlBrainGateway
from ...datamake.resources.sql_adapter import SqlResourceAdapter
from ...datamake.resources.sql_schema_provider import SqlSchemaProvider
from ...datamake.runtime.compiler import ExecutionCompiler
from ...datamake.runtime.compiled_dag_executor import CompiledDagExecutor
from ...datamake.runtime.execution import ActionExecutor
from ...datamake.runtime.executor import RuntimeExecutor
from ...datamake.runtime.legacy_scenario_executor import LegacyScenarioExecutor
from ...datamake.runtime.probe import ProbeExecutor
from ...datamake.runtime.recovery import RecoveryCoordinator
from ...datamake.runtime.template_version_executor import TemplateVersionExecutor
from ...datamake.services.compiled_dag_service import CompiledDagService
from ...datamake.services.flow_draft_aggregate_service import FlowDraftAggregateService
from ...datamake.services.recall_service import RecallService
from ...datamake.services.approval_service import ApprovalService
from ...datamake.services.draft_service import DraftService
from ...datamake.services.template_draft_service import TemplateDraftService
from ...datamake.services.template_embedding_resolver import (
    resolve_template_embedding_from_env,
)
from ...datamake.services.template_publish_service import TemplatePublishService
from ...datamake.services.template_retrieval_service import TemplateRetrievalService
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

    当前真实职责：
    - 仍然是 datamake 的顶层入口壳，对外暴露 `run()` 生命周期
    - 内部装配主循环所需的 dispatch / guard / runtime / ledger / template 依赖
    - 协调等待态恢复、结构化草稿持久化、Prompt 组装与 LLM 决策

    当前已接入能力：
    - interaction / supervision / execution 三类动作分发
    - SQL / HTTP / compiled DAG / template publish / template execute
    - pending interaction / approval 的恢复执行
    - flow draft aggregate、compiled DAG、template retrieval/publish 链路

    当前仍然存在的工程问题：
    - 这个类仍偏重，属于“入口壳 + 主循环 + 一部分编排胶水”共存状态
    - 因此后续会继续把 pending reply 协调、Prompt 组装、主循环执行逐步下沉
    - 但下沉过程中不会破坏现有唯一控制律与 Guard/Runtime/Resource 骨架
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
        # 下面这些组件一起构成第一阶段最小闭环。
        # 它们都尽量贴着你的五层架构来组织，而不是重新回退成“大 Pattern 全包”。
        self.snapshot_builder = SnapshotBuilder(self.ledger_repository)
        self.termination_resolver = TerminationResolver()
        self.approval_service = None
        self.draft_service = None
        self.flow_draft_aggregate_service = None
        self.compiled_dag_service = None
        self.template_draft_service = None
        self.template_publish_service = None
        self.template_retrieval_service = None
        if hasattr(self.ledger_repository, "session_factory"):
            template_embedding_model = resolve_template_embedding_from_env()
            self.approval_service = ApprovalService(
                self.ledger_repository.session_factory
            )
            self.draft_service = DraftService(self.ledger_repository.session_factory)
            self.flow_draft_aggregate_service = FlowDraftAggregateService(
                self.ledger_repository.session_factory
            )
            self.compiled_dag_service = CompiledDagService(
                self.ledger_repository.session_factory
            )
            self.template_draft_service = TemplateDraftService(
                self.ledger_repository.session_factory
            )
            self.template_publish_service = TemplatePublishService(
                self.ledger_repository.session_factory
            )
            self.template_retrieval_service = TemplateRetrievalService(
                self.ledger_repository.session_factory,
                embedding_model=template_embedding_model,
            )
        self.interaction_bridge = InteractionBridge()
        self.supervision_bridge = SupervisionBridge(self.approval_service)
        self.ui_response_mapper = UiResponseMapper()
        self.agent_capability_adapter = DataMakeAgentCapabilityAdapter()
        self.prompt_builder = DataMakePromptBuilder()
        self.evidence_budget_manager = EvidenceBudgetManager(
            compact_config=self.compact_config,
            compact_llm=self.compact_llm,
            extract_content=self._extract_content,
        )
        self.decision_provider = DataMakeDecisionProvider(
            llm=self.llm,
            tracer=self.tracer,
            prompt_builder=self.prompt_builder,
            evidence_budget_manager=self.evidence_budget_manager,
        )
        self.resource_registration_coordinator = DataMakeResourceRegistrationCoordinator(
            resource_catalog=self.resource_catalog,
        )
        self.flow_draft_sync_coordinator = FlowDraftSyncCoordinator(
            draft_service=self.draft_service,
            flow_draft_aggregate_service=self.flow_draft_aggregate_service,
        )
        self.pattern_hook_adapter = PatternHookAdapter(tracer=self.tracer)

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
        self.compiled_dag_executor = CompiledDagExecutor(
            self.action_executor,
            execution_compiler=self.execution_compiler,
        )
        self.template_version_executor = TemplateVersionExecutor(
            compiled_dag_executor=self.compiled_dag_executor,
            session_factory=getattr(self.ledger_repository, "session_factory", None),
        )
        self.legacy_scenario_executor = LegacyScenarioExecutor(
            template_version_executor=self.template_version_executor,
        )
        self.compiled_dag_executor.template_version_executor = self.template_version_executor
        self.compiled_dag_executor.legacy_scenario_executor = self.legacy_scenario_executor
        self.runtime_executor = RuntimeExecutor(
            self.execution_compiler,
            self.probe_executor,
            self.action_executor,
            flow_draft_aggregate_service=self.flow_draft_aggregate_service,
            compiled_dag_service=self.compiled_dag_service,
            template_draft_service=self.template_draft_service,
            template_publish_service=self.template_publish_service,
            compiled_dag_executor=self.compiled_dag_executor,
            template_version_executor=self.template_version_executor,
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
        self.pending_reply_coordinator = PendingReplyCoordinator(
            ledger_repository=self.ledger_repository,
            interaction_bridge=self.interaction_bridge,
            supervision_bridge=self.supervision_bridge,
            ui_response_mapper=self.ui_response_mapper,
            guard_service=self.guard_service,
            recovery_coordinator=self.recovery_coordinator,
            pattern_hook_adapter=self.pattern_hook_adapter,
        )
        runner_ports = DataMakeRunnerPorts(
            dispatcher=self.dispatcher,
            ledger_repository=self.ledger_repository,
            tracer=self.tracer,
            max_iterations=self.max_iterations,
            consume_pending_replies=self._consume_pending_replies,
            persist_flow_draft_if_present=self.flow_draft_sync_coordinator.persist_if_present,
            recover_waiting_state=self.pending_reply_coordinator.recover_waiting_state,
            get_next_action_decision=self.decision_provider.get_next_action_decision,
            hydrate_internal_decision_state=self._hydrate_internal_decision_state,
        )
        runner_hooks = DataMakeRunnerHooks(
            trace_decision_output=self._trace_decision_output,
            trace_paused_result=self._trace_paused_result,
            trace_final_result=self._trace_final_result,
            trace_error_result=self._trace_error_result,
            build_waiting_user_result=self._build_waiting_user_result,
            build_waiting_human_result=self._build_waiting_human_result,
        )
        self.decision_runner = DataMakeDecisionRunner(
            ports=runner_ports,
            hooks=runner_hooks,
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
        await self.pattern_hook_adapter.trace_run_start(
            task_id=task_id,
            task=task,
            max_iterations=self.max_iterations,
            tools=tools,
            step_id=step_id,
            step_name=step_name,
            file_info=context.state.get(CONTEXT_KEY_FILE_INFO),
            uploaded_files=context.state.get(CONTEXT_KEY_UPLOADED_FILES),
        )

        try:
            self.resource_registration_coordinator.prepare_run_resources(
                context=context,
                tools=tools,
            )
            recall_service = RecallService(memory)
            decision_builder = DecisionBuilder(
                self.snapshot_builder,
                recall_service,
                self.draft_service,
                self.resource_catalog,
                template_retrieval_service=self.template_retrieval_service,
                capability_adapter=self.agent_capability_adapter,
            )
            run_result = await self.decision_runner.run(
                DataMakeRunInput(
                    task=task,
                    context=context,
                    decision_builder=decision_builder,
                    task_id=task_id,
                    step_id=step_id,
                    step_name=step_name,
                )
            )
            return run_result.to_response_payload()
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

        这里保留 Pattern 内部方法名，是为了兼容现有调用点；
        真实消费逻辑已经下沉到 `PendingReplyCoordinator`，
        让 Pattern 不再直接承载 interaction / approval 的细节。
        """
        return await self.pending_reply_coordinator.consume_pending_replies(context)

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
        return await self.decision_provider.get_next_action_decision(
            task,
            round_context,
            context,
            task_id,
            step_id,
            round_id,
        )

    def _build_llm_messages(
        self,
        task: str,
        round_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        构建提供给 LLM 的当前轮消息。

        这里保留原方法名，是为了兼容现有测试和调用点；
        真实 Prompt 组装已经下沉到 `DataMakePromptBuilder`。
        """
        return self.decision_provider.build_llm_messages(task, round_context)

    def _parse_decision_payload(self, payload: Any) -> NextActionDecision:
        """
        将外部 payload 解析为 `NextActionDecision`。

        这里显式兼容：
        - pydantic model
        - dict
        - llm.chat() 返回的 json 字符串
        """
        return self.decision_provider.parse_decision_payload(payload)

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
        decision.params["_system_task_id"] = context.task_id
        if context.user_id:
            decision.params["_system_user_id"] = context.user_id

    def _register_resource_actions_from_context(self, context: AgentContext) -> None:
        """
        从 `context.state` 注册第一阶段可用的资源动作。

        这样做的好处是：
        - 不强依赖数据库配置中心
        - 先让最小闭环可以用内存配置跑通
        - 未来再替换成正式注册中心读取逻辑时，Pattern 主循环不用大改
        """
        self.resource_registration_coordinator.register_resource_actions_from_context(context)

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
        return self.resource_registration_coordinator.build_registration_signature(
            context=context,
            tools=tools,
        )

    async def _persist_flow_draft_if_present(self, context: AgentContext) -> None:
        """
        若当前上下文已携带 flow_draft，则优先把它吸收到结构化 aggregate 宿主。

        设计意图：
        - `context.state["flow_draft"]` 仍然允许作为当前轮工作记忆输入；
        - 但真正的持久化真相源应是 `FlowDraftAggregate`；
        - 持久化完成后，再把 aggregate 的 projection 回写到 context.state，
          避免下一阶段 round context 继续消费一份未规范化的临时 JSON。
        """
        await self.flow_draft_sync_coordinator.persist_if_present(context)

    def _estimate_message_tokens(self, messages: list[dict[str, str]]) -> int:
        """
        估算当前消息的 token 数。
        """

        return self.decision_provider.estimate_message_tokens(messages)

    async def _check_and_compact_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        在调用 LLM 前检查上下文长度，必要时执行压缩。

        这里保留 Pattern 内部方法名，是为了兼容现有测试和调用点；
        真实证据预算与 compact 逻辑已经下沉到 `EvidenceBudgetManager`。
        """

        return await self.decision_provider.check_and_compact_context(messages)

    async def _compact_datamake_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        对 datamake 当前轮消息做压缩。

        真实逻辑已经下沉到 `EvidenceBudgetManager`，这里只保留薄代理。
        """

        return await self.decision_provider.compact_datamake_context(messages)

    def _fallback_truncate_messages(
        self,
        messages: list[dict[str, str]],
        original_tokens: int,
    ) -> list[dict[str, str]]:
        """
        压缩失败时的兜底截断逻辑。
        """

        return self.decision_provider.fallback_truncate_messages(messages, original_tokens)

    def _parse_compact_response(self, response: str) -> list[dict[str, str]]:
        """
        解析压缩模型返回的 `SYSTEM: ... / USER: ...` 文本。
        """

        return self.decision_provider.parse_compact_response(response)

    def _extract_content(self, response: Any) -> str:
        """
        从 xagent LLM 返回结果中提取文本内容。
        """
        return self.decision_provider.extract_content(response)

    def get_compact_stats(self) -> dict[str, Any]:
        """
        返回当前上下文压缩统计信息。
        """

        return self.evidence_budget_manager.get_stats()

    def _resolve_trace_step_context(self, task_id: str) -> tuple[str, str]:
        """
        为 datamake 当前运行构造稳定的 step 上下文。
        """
        return self.pattern_hook_adapter.resolve_trace_step_context(task_id)

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
        return self.pattern_hook_adapter.build_user_trace_data(
            task=task,
            tools=tools,
            step_id=step_id,
            step_name=step_name,
            file_info=context.state.get(CONTEXT_KEY_FILE_INFO),
            uploaded_files=context.state.get(CONTEXT_KEY_UPLOADED_FILES),
        )

    def _build_waiting_user_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """
        组装 `waiting_user` 的对外返回结构。

        这里保留 Pattern 私有方法名，是为了让 `DecisionRunner` 继续通过 callback 调用；
        真正的组装逻辑已经下沉到 `PatternHookAdapter`。
        """

        return self.pattern_hook_adapter.build_waiting_user_result(
            question=question,
            field=field,
            chat_payload=chat_payload,
            ticket_id=ticket_id,
        )

    def _build_waiting_human_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        approval_id: str,
    ) -> dict[str, Any]:
        """
        组装 `waiting_human` 的对外返回结构。
        """

        return self.pattern_hook_adapter.build_waiting_human_result(
            question=question,
            field=field,
            chat_payload=chat_payload,
            approval_id=approval_id,
        )

    async def _trace_decision_output(
        self,
        task_id: str,
        decision: NextActionDecision,
        round_id: int,
    ) -> None:
        """
        记录当前轮 AI 决策输出。
        """

        await self.pattern_hook_adapter.trace_decision_output(
            task_id,
            decision,
            round_id,
        )

    async def _trace_run_result(self, task_id: str, result: dict[str, Any]) -> None:
        """
        记录本次 run 返回给外部调用方的结果摘要。
        """

        await self.pattern_hook_adapter.trace_run_result(task_id, result)

    async def _trace_paused_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        result: dict[str, Any],
        recovered: bool = False,
    ) -> None:
        """
        记录等待态返回。

        这类结果是主循环的“暂停点”而不是失败点，后续无论来源是：
        - pending reply 恢复
        - 新建 waiting_user / waiting_human
        都统一走同一个 hook 收口。
        """

        await self.pattern_hook_adapter.trace_paused_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            result=result,
            recovered=recovered,
        )

    async def _trace_final_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        payload: dict[str, Any],
        iterations: int,
    ) -> None:
        """
        记录最终结束结果。
        """

        await self.pattern_hook_adapter.trace_final_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            payload=payload,
            iterations=iterations,
        )

    async def _trace_error_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        result: dict[str, Any],
        consecutive_failures: int,
    ) -> None:
        """
        记录连续失败达到阈值后的错误返回。
        """

        await self.pattern_hook_adapter.trace_error_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            result=result,
            consecutive_failures=consecutive_failures,
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

        await self.pattern_hook_adapter.trace_pattern_failure(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            task=task,
            exc=exc,
        )
