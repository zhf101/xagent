"""智能造数平台会话编排器。

目标：
- 收口 websocket 里的 data_generation 会话门控重复逻辑
- 统一“首轮召回 -> 会话决策 -> 是否暂停给用户 -> 是否放行执行”的过程
- 让后续 websocket 入口逐步退化成薄适配层
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xagent.core.workspace import TaskWorkspace
from xagent.datamakepool.interceptors import ApprovalGate
from xagent.datamakepool.orchestration import TemplateRunExecutor
from xagent.web.config import UPLOADS_DIR
from xagent.web.tools.config import WebToolConfig
from xagent.web.models.task import Task

from .response_builder import ConversationResponseBuilder
from .runtime_service import ConversationRuntimeService
from .service import DataGenerationConversationDecision, DataGenerationConversationService


@dataclass
class ConversationGateResult:
    should_pause: bool
    session: Any
    decision: DataGenerationConversationDecision
    response_payload: dict[str, Any] | None = None
    execution_context: dict[str, Any] | None = None


@dataclass
class ConversationExecutionPreparation:
    task_context: dict[str, Any]
    planning_decision: Any
    params: dict[str, Any]
    match_result: Any
    generation_system_short: str | None
    session: Any
    gate_result: ConversationGateResult | None = None
    should_attempt_template_direct: bool = False


@dataclass
class TemplateDirectHandlingResult:
    should_return: bool
    response_payload: dict[str, Any] | None = None
    refresh_prompt_recommendation: bool = False


@dataclass
class ApprovalPauseResult:
    requires_pause: bool
    response_payload: dict[str, Any] | None = None


class DataGenerationConversationOrchestrator:
    """收口 data_generation 会话门控的最小编排器。"""

    def __init__(self, db, *, user_id: int | None = None):
        self._db = db
        self._service = DataGenerationConversationService(db, user_id=user_id)
        self._runtime = ConversationRuntimeService(db)

    @property
    def service(self) -> DataGenerationConversationService:
        return self._service

    def build_recall_context(self, *, entry_recall: Any) -> dict[str, Any]:
        """把入口统一召回结果转换成 task_context 可消费的稳定结构。"""

        planning_decision = entry_recall.template_decision
        match_result = planning_decision.match_result
        context: dict[str, Any] = {
            "entry_recall_result": {
                "selected_strategy": entry_recall.selected_strategy,
                "selected_candidate": self._serialize_candidate(
                    entry_recall.selected_candidate
                ),
                "template_candidates": [
                    self._serialize_candidate(candidate)
                    for candidate in entry_recall.template_candidates
                ],
                "sql_asset_candidates": [
                    self._serialize_candidate(candidate)
                    for candidate in entry_recall.sql_asset_candidates
                ],
                "http_asset_candidates": [
                    self._serialize_candidate(candidate)
                    for candidate in entry_recall.http_asset_candidates
                ],
                "legacy_candidates": [
                    self._serialize_candidate(candidate)
                    for candidate in entry_recall.legacy_candidates
                ],
                "missing_params": list(entry_recall.missing_params or []),
                "debug": dict(entry_recall.debug or {}),
            },
            "datamakepool_match_type": match_result.match_type,
            "datamakepool_execution_plan": planning_decision.execution_plan,
            "datamakepool_template_match": {
                "match_type": match_result.match_type,
                "coverage_score": match_result.coverage_score,
                "confidence": match_result.confidence,
                "covered_requirements": match_result.covered_requirements,
                "missing_requirements": match_result.missing_requirements,
                "recall_strategy": match_result.recall_strategy,
                "used_ann": match_result.used_ann,
                "used_fallback": match_result.used_fallback,
                "stage_results": match_result.stage_results,
            },
        }
        if match_result.matched_template:
            context["datamakepool_template_match"]["matched_template"] = {
                "template_id": match_result.matched_template.template_id,
                "template_name": match_result.matched_template.template_name,
                "version": match_result.matched_template.version,
                "system_short": match_result.matched_template.system_short,
            }

        guidance = self._build_selected_candidate_guidance(entry_recall)
        if guidance:
            context["system_prompt"] = guidance
        return context

    def evaluate_gate(
        self,
        *,
        task: Task,
        user_id: int,
        user_message: str,
        entry_recall: Any | None = None,
        trigger_event_type: str,
    ) -> ConversationGateResult:
        session = self._service.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )
        if session.state == "created":
            if entry_recall is None:
                raise ValueError(
                    "entry_recall is required when evaluating a created session"
                )
            decision = self._service.build_initial_decision(
                task=task,
                user_id=user_id,
                goal=str(task.description or user_message),
                entry_recall=entry_recall,
            )
        else:
            decision = self._service.consume_user_message(
                task=task,
                user_id=user_id,
                user_message=user_message,
            )

        session = self._service.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )

        if decision.should_pause_for_user and decision.chat_response:
            payload = ConversationResponseBuilder.build_task_completed_payload(
                task=task,
                session=session,
                success=True,
                result_text=decision.chat_response.get("message", ""),
                execution_type="datamakepool_conversation_gate",
                chat_response=decision.chat_response,
                ui=decision.ui,
            )
            return ConversationGateResult(
                should_pause=True,
                session=session,
                decision=decision,
                response_payload=payload,
            )

        execution_context = dict(decision.execution_context or {})
        if execution_context:
            execution_run = self._runtime.create_execution_run(
                session=session,
                task_id=int(task.id),
                run_type=(
                    "direct_execute"
                    if execution_context.get("datamakepool_execution_choice")
                    == "direct_execute"
                    else "planned_execute"
                ),
                linked_draft_id=execution_context.get("datamakepool_active_flow_draft_id"),
                trigger_event_type=trigger_event_type,
                target_ref=str(
                    execution_context.get("datamakepool_selected_candidate_id") or ""
                )
                or None,
                input_payload={
                    "compiled_dag": execution_context.get("datamakepool_compiled_dag"),
                    "facts": dict(
                        execution_context.get("datamakepool_conversation_facts") or {}
                    ),
                },
            )
            execution_context["datamakepool_execution_run_id"] = int(execution_run.id)

        return ConversationGateResult(
            should_pause=False,
            session=session,
            decision=decision,
            execution_context=execution_context,
        )

    def prepare_execution(
        self,
        *,
        task: Task,
        user_id: int,
        task_context: dict[str, Any],
        entry_recall: Any,
        trigger_event_type: str,
    ) -> ConversationExecutionPreparation:
        """把 data_generation 的执行前准备收口到会话编排器。"""

        planning_decision = entry_recall.template_decision
        params = dict(planning_decision.params or {})
        match_result = planning_decision.match_result
        generation_system_short = params.get("system_short")

        prepared_context = dict(task_context)
        prepared_context.update(self.build_recall_context(entry_recall=entry_recall))

        session = self._service.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or ""),
        )

        gate_result: ConversationGateResult | None = None
        if session.state in {"created", "awaiting_choice", "clarifying"}:
            gate_result = (
                self.evaluate_gate(
                    task=task,
                    user_id=user_id,
                    user_message=str(task.description),
                    entry_recall=entry_recall,
                    trigger_event_type=trigger_event_type,
                )
                if session.state == "created"
                else self.evaluate_gate(
                    task=task,
                    user_id=user_id,
                    user_message="",
                    trigger_event_type=trigger_event_type,
                )
            )
            if gate_result.execution_context:
                prepared_context.update(gate_result.execution_context)
                session = gate_result.session

        if (
            planning_decision.execution_path == "template_direct"
            and prepared_context.get("datamakepool_execution_choice")
            != "direct_execute"
        ):
            planning_decision.route_to_orchestrator = True
            prepared_context["system_prompt"] = (
                prepared_context.get("system_prompt", "")
                + "\n\n用户未选择模板直跑，本轮改为进入会话确认后的规划执行路径。"
            ).strip()

        should_attempt_template_direct = bool(
            planning_decision.execution_path == "template_direct"
            and match_result.matched_template
            and prepared_context.get("datamakepool_execution_choice")
            == "direct_execute"
        )

        return ConversationExecutionPreparation(
            task_context=prepared_context,
            planning_decision=planning_decision,
            params=params,
            match_result=match_result,
            generation_system_short=generation_system_short,
            session=session,
            gate_result=gate_result,
            should_attempt_template_direct=should_attempt_template_direct,
        )

    async def handle_template_direct(
        self,
        *,
        task: Task,
        task_id: int,
        user: Any,
        task_context: dict[str, Any],
        planning_decision: Any,
        match_result: Any,
        params: dict[str, Any],
        session: Any,
        event_callback: Any,
    ) -> TemplateDirectHandlingResult:
        """处理模板直跑分析、直跑成功和回退准备。"""

        if not (
            planning_decision.execution_path == "template_direct"
            and match_result.matched_template
            and task_context.get("datamakepool_execution_choice") == "direct_execute"
        ):
            return TemplateDirectHandlingResult(False)

        execution_run_id = task_context.get("datamakepool_execution_run_id")

        class TemplateDirectRequest:
            def __init__(self, user_id: int, is_admin: bool):
                self.user: Any = type(
                    "obj",
                    (),
                    {"id": user_id, "is_admin": is_admin},
                )()
                self.credentials: Any = None

        workspace = TaskWorkspace(
            id=f"web_task_{task_id}",
            base_dir=str(UPLOADS_DIR / f"user_{user.id}"),
        )
        direct_tool_config = WebToolConfig(
            db=self._db,
            request=TemplateDirectRequest(int(user.id), bool(user.is_admin)),
            user_id=int(user.id),
            is_admin=bool(user.is_admin),
            include_mcp_tools=False,
            task_id=str(task_id),
            browser_tools_enabled=False,
        )
        template_executor = TemplateRunExecutor(
            self._db,
            workspace=workspace,
            mcp_configs=direct_tool_config.get_mcp_server_configs(),
            user_id=int(user.id),
            event_callback=event_callback,
        )
        direct_support = template_executor.analyze_match(
            match_result.matched_template,
            params,
        )
        task_context["datamakepool_template_direct_support"] = direct_support.to_dict()
        task_context["datamakepool_template_match"][
            "direct_execution_supported"
        ] = direct_support.executable
        task_context["datamakepool_template_match"][
            "direct_execution_reason"
        ] = direct_support.reason

        if direct_support.executable:
            template_result = await template_executor.execute_match(
                task_id=int(task_id),
                created_by=int(user.id),
                matched=match_result.matched_template,
                params=params,
            )
            if getattr(template_result, "paused", False):
                task.status = task.status.__class__.PAUSED
            else:
                task.status = (
                    task.status.__class__.COMPLETED
                    if template_result.success
                    else task.status.__class__.FAILED
                )
            self._db.add(task)
            self._db.commit()
            if execution_run_id:
                self._runtime.finish_execution_run(
                    run_id=int(execution_run_id),
                    status=(
                        "paused"
                        if getattr(template_result, "paused", False)
                        else "completed"
                        if template_result.success
                        else "failed"
                    ),
                    summary=str(template_result.output or ""),
                    result_payload={
                        "success": bool(template_result.success),
                        "metadata": template_result.metadata or {},
                    },
                )
            if getattr(template_result, "paused", False):
                approval = (
                    template_result.metadata.get("approval")
                    if isinstance(template_result.metadata, dict)
                    else None
                )
                payload = ConversationResponseBuilder.build_task_paused_payload(
                    task=task,
                    session=session,
                    message=str(template_result.output or ""),
                    approval=approval,
                    metadata=template_result.metadata or {},
                )
            else:
                payload = ConversationResponseBuilder.build_task_completed_payload(
                    task=task,
                    session=session,
                    success=bool(template_result.success),
                    result_text=str(template_result.output or ""),
                    execution_type="datamakepool_direct_execute",
                    extra_metadata=template_result.metadata or {},
                )
            return TemplateDirectHandlingResult(
                should_return=True,
                response_payload=payload,
                refresh_prompt_recommendation=bool(template_result.success),
            )

        planning_decision.route_to_orchestrator = True
        fallback_summary = (
            "模板命中但当前不能安全直跑，已自动回退 orchestrator。"
            f"原因：{direct_support.reason}"
        )
        if isinstance(task_context.get("datamakepool_execution_plan"), dict):
            task_context["datamakepool_execution_plan"][
                "template_direct_fallback"
            ] = direct_support.to_dict()
        task_context["datamakepool_template_direct_fallback"] = direct_support.to_dict()
        task_context["system_prompt"] = (
            task_context.get("system_prompt", "") + "\n\n" + fallback_summary
        ).strip()
        return TemplateDirectHandlingResult(False)

    def evaluate_runtime_approval(
        self,
        *,
        task: Task,
        task_id: int,
        requester_id: int,
        domain_mode: str,
        system_short: str | None = None,
        execution_kind: str | None = None,
    ) -> ApprovalPauseResult:
        """评估运行时审批，并构造暂停响应。"""

        decision = ApprovalGate(self._db).evaluate(
            task_id=int(task_id),
            task_description=str(task.description),
            domain_mode=domain_mode,
            requester_id=int(requester_id),
            system_short=system_short,
            execution_kind=execution_kind,
        )
        if not decision.requires_approval:
            return ApprovalPauseResult(False)

        session = self._service.get_or_create_session(
            task=task,
            user_id=int(requester_id),
            goal=str(task.description or ""),
        )
        session.state = "paused_for_user"
        session.latest_summary = str(decision.reason)
        self._db.add(session)
        task.status = task.status.__class__.PAUSED
        self._db.add(task)
        self._db.commit()

        payload = ConversationResponseBuilder.build_task_paused_payload(
            task=task,
            session=session,
            message="Task paused for approval",
            approval={
                "ticket_id": decision.ticket_id,
                "required_role": decision.required_role,
                "reason": decision.reason,
                "system_short": system_short,
            },
            metadata={
                "execution_type": "datamakepool_approval_pause",
            },
        )
        return ApprovalPauseResult(True, response_payload=payload)

    def _build_selected_candidate_guidance(self, entry_recall: Any) -> str:
        selected_candidate = entry_recall.selected_candidate
        if selected_candidate is None or entry_recall.selected_strategy not in {
            "sql_asset_direct",
            "http_asset_direct",
            "legacy_direct",
        }:
            return ""
        missing_param_labels = [
            item.get("label") or item.get("field")
            for item in entry_recall.missing_params
        ]
        guidance = (
            "\n\n入口统一召回已完成："
            f"\n- selected_strategy={entry_recall.selected_strategy}"
            f"\n- selected_candidate={selected_candidate.display_name}"
            f"\n- matched_signals={selected_candidate.matched_signals}"
        )
        if missing_param_labels:
            guidance += (
                "\n- 你接下来若需要向用户补参，只能优先围绕这些字段提问："
                + "、".join(str(item) for item in missing_param_labels if item)
            )
        return guidance

    @staticmethod
    def _serialize_candidate(candidate: Any) -> dict[str, Any] | None:
        if candidate is None:
            return None
        return {
            "source_type": getattr(candidate, "source_type", None),
            "candidate_id": getattr(candidate, "candidate_id", None),
            "display_name": getattr(candidate, "display_name", None),
            "system_short": getattr(candidate, "system_short", None),
            "score": getattr(candidate, "score", None),
            "matched_signals": list(getattr(candidate, "matched_signals", []) or []),
            "payload": getattr(candidate, "payload", None),
            "summary": getattr(candidate, "summary", None),
        }
