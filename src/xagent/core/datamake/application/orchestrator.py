"""
应用编排辅助模块。

这里放的是顶层主脑的“辅助编排器”，不是第二个主脑。
当前阶段最重要的职责，是把散落在 `context.state`、Recall、Ledger 中的信息
收敛成一份稳定的 `Round Context`（单轮上下文）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ..ledger.snapshots import SnapshotBuilder
from ..resources.sql_resource_definition import parse_sql_resource_metadata
from ..services.compiled_dag_service import CompiledDagService
from ..services.draft_service import DraftService
from ..services.flow_draft_aggregate_service import FlowDraftAggregateService
from ..services.recall_service import RecallService
from ..services.template_draft_service import TemplateDraftService
from ..services.template_embedding_resolver import (
    resolve_template_embedding_from_env,
)
from ..services.template_publish_service import TemplatePublishService
from ..services.template_retrieval_service import TemplateRetrievalService
from .agent_capability_adapter import DataMakeAgentCapabilityAdapter

if TYPE_CHECKING:
    from ...agent.context import AgentContext
    from ..resources.catalog import ResourceCatalog


class DecisionBuilder:
    """
    `DecisionBuilder`（决策上下文构建器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`Agent Control Plane`（Agent 控制平面）的辅助组件
    - 在你的设计里：单轮推理前的数据拼装器

    当前实现的目标很明确：
    - 让主脑不需要自己去拼 `context.state`、Recall、Ledger。
    - 让每一轮给 LLM 的输入都遵循稳定结构，后续更容易扩展 prompt。
    """

    def __init__(
        self,
        snapshot_builder: SnapshotBuilder,
        recall_service: Optional[RecallService] = None,
        draft_service: Optional[DraftService] = None,
        resource_catalog: Optional[ResourceCatalog] = None,
        flow_draft_aggregate_service: Optional[FlowDraftAggregateService] = None,
        compiled_dag_service: Optional[CompiledDagService] = None,
        template_draft_service: Optional[TemplateDraftService] = None,
        template_publish_service: Optional[TemplatePublishService] = None,
        template_retrieval_service: Optional[TemplateRetrievalService] = None,
        capability_adapter: Optional[DataMakeAgentCapabilityAdapter] = None,
    ) -> None:
        self.snapshot_builder = snapshot_builder
        self.recall_service = recall_service
        self.draft_service = draft_service
        self.resource_catalog = resource_catalog
        self.flow_draft_aggregate_service = flow_draft_aggregate_service
        self.compiled_dag_service = compiled_dag_service
        self.template_draft_service = template_draft_service
        self.template_publish_service = template_publish_service
        self.template_retrieval_service = template_retrieval_service
        self.capability_adapter = capability_adapter

        # 这里允许基于 DraftService 共享同一 session_factory 自动补齐查询服务，
        # 目的只是复用已持久化证据，不是让 orchestrator 变成新的业务编排器。
        if self.flow_draft_aggregate_service is None and draft_service is not None:
            session_factory = getattr(draft_service, "session_factory", None)
            if session_factory is not None:
                self.flow_draft_aggregate_service = FlowDraftAggregateService(session_factory)
        if self.compiled_dag_service is None and draft_service is not None:
            session_factory = getattr(draft_service, "session_factory", None)
            if session_factory is not None:
                self.compiled_dag_service = CompiledDagService(session_factory)
        if self.template_draft_service is None and draft_service is not None:
            session_factory = getattr(draft_service, "session_factory", None)
            if session_factory is not None:
                self.template_draft_service = TemplateDraftService(session_factory)
        if self.template_publish_service is None and draft_service is not None:
            session_factory = getattr(draft_service, "session_factory", None)
            if session_factory is not None:
                self.template_publish_service = TemplatePublishService(session_factory)
        if self.template_retrieval_service is None and draft_service is not None:
            session_factory = getattr(draft_service, "session_factory", None)
            if session_factory is not None:
                self.template_retrieval_service = TemplateRetrievalService(
                    session_factory,
                    embedding_model=resolve_template_embedding_from_env(),
                )
        if self.capability_adapter is None:
            self.capability_adapter = DataMakeAgentCapabilityAdapter()

    async def build_round_context(
        self,
        task: str,
        context: AgentContext,
    ) -> dict[str, Any]:
        """
        构建 `Round Context`（单轮上下文）。

        当前阶段输出重点包含：
        - 当前任务文本
        - AgentContext 中已有状态
        - Ledger 最新快照
        - Recall 结果
        """

        ledger_snapshot = await self.snapshot_builder.build(context.task_id)
        recall_results: list[dict[str, Any]] = []
        persisted_aggregate = None
        persisted_draft: dict[str, Any] = {}
        compiled_dag_digest: dict[str, Any] | None = None
        template_draft_digest: dict[str, Any] | None = None
        template_version_digest: dict[str, Any] | None = None
        template_version_candidates: list[dict[str, Any]] = []

        if self.recall_service is not None:
            recall_results = await self.recall_service.search(task)
        if self.flow_draft_aggregate_service is not None:
            persisted_aggregate = await self.flow_draft_aggregate_service.load(context.task_id)
            if persisted_aggregate is not None:
                persisted_draft = self.flow_draft_aggregate_service.projection_service.to_state(
                    persisted_aggregate
                ).model_dump(mode="json")
        elif self.draft_service is not None:
            loaded_draft = await self.draft_service.load(context.task_id)
            if loaded_draft is not None:
                persisted_draft = loaded_draft.model_dump(mode="json")
        if self.compiled_dag_service is not None:
            compiled_dag_digest = await self.compiled_dag_service.load_digest(context.task_id)
        if self.template_draft_service is not None:
            digest = await self.template_draft_service.load_latest_digest(context.task_id)
            template_draft_digest = digest.model_dump(mode="json") if digest is not None else None
        if self.template_publish_service is not None:
            digest = await self.template_publish_service.load_latest_digest(context.task_id)
            template_version_digest = (
                digest.model_dump(mode="json") if digest is not None else None
            )

        # 结构化 aggregate 的 projection 应是主链真相源。
        # 只有在当前运行没有持久化 draft 宿主时，才退回使用 context.state 中的临时 draft。
        flow_draft = dict(persisted_draft)
        state_draft = context.state.get("flow_draft")
        if not flow_draft and isinstance(state_draft, dict):
            flow_draft.update(state_draft)

        if self.template_retrieval_service is not None:
            retrieval_flow_draft: Any = persisted_aggregate if persisted_aggregate is not None else flow_draft
            candidate_items = await self.template_retrieval_service.search_candidates(
                task=task,
                flow_draft=retrieval_flow_draft,
                current_user_id=context.user_id,
                limit=3,
            )
            template_version_candidates = [
                item.model_dump(mode="json") for item in candidate_items
            ]

        # 把当前已注册的受控资源动作摘要注入上下文，
        # 让主脑知道本轮可以调用哪些 execution_action，不需要猜测。
        available_resources: list[dict[str, Any]] = []
        if self.resource_catalog is not None:
            for action_def in self.resource_catalog.registry.list_all():
                metadata = parse_sql_resource_metadata(action_def.metadata)
                available_resources.append(
                    {
                        "resource_key": action_def.resource_key,
                        "operation_key": action_def.operation_key,
                        "adapter_kind": action_def.adapter_kind,
                        "description": action_def.description,
                        "risk_level": action_def.risk_level,
                        "supports_probe": action_def.supports_probe,
                        "requires_approval": action_def.requires_approval,
                        "resource_policy": {
                            "sql_brain_enabled": metadata.sql_brain_enabled,
                            "read_only": metadata.datasource.read_only,
                            "db_type": metadata.datasource.db_type,
                            "connection_name": metadata.datasource.connection_name,
                            "datasource_id": metadata.datasource.datasource_id,
                            "text2sql_database_id": metadata.datasource.text2sql_database_id,
                        },
                        "sql_context_hints": self._build_sql_context_hints(
                            action_def=action_def,
                            recall_results=recall_results,
                        ),
                    }
                )

        capability_context = (
            await self.capability_adapter.build_round_capability_context(context=context)
            if self.capability_adapter is not None
            else {}
        )
        evidence_layers = self._build_evidence_layers(
            available_resources=available_resources,
            recall_results=recall_results,
            template_version_candidates=template_version_candidates,
            external_content_evidence=capability_context.get("external_content_evidence") or [],
            skill_catalog_summaries=capability_context.get("skill_catalog_summaries") or [],
        )

        return {
            "task_id": context.task_id,
            "session_id": context.session_id,
            "task": task,
            "user_id": context.user_id,
            "system_prompt": context.state.get("system_prompt"),
            "flow_draft": flow_draft,
            "available_resources": available_resources,
            "context_state": context.state,
            "history": list(context.history),
            "recall_results": recall_results,
            "compiled_dag_digest": compiled_dag_digest,
            "template_draft_digest": template_draft_digest,
            "template_version_digest": template_version_digest,
            "template_version_candidates": template_version_candidates,
            "ledger_snapshot": ledger_snapshot,
            "file_info": context.state.get("file_info"),
            "uploaded_files": context.state.get("uploaded_files"),
            "evidence_layers": evidence_layers,
            **capability_context,
        }

    def _build_sql_context_hints(
        self,
        *,
        action_def: Any,
        recall_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        为单个 SQL 资源动作构建 recall 驱动的 SQL 材料提示。

        注意这仍然只是 hint，不是系统事实：
        - 仅当 recall_service 可用且该资源启用了 SQL Brain 时才提供
        - 主脑若决定采用，必须显式写回 `params.sql_context`
        """

        if self.recall_service is None:
            return None

        metadata = parse_sql_resource_metadata(action_def.metadata)
        if action_def.adapter_kind != "sql":
            return None
        if not metadata.sql_brain_enabled:
            return None

        hint = self.recall_service.build_sql_context_hints(
            recall_results,
            resource_key=action_def.resource_key,
            operation_key=action_def.operation_key,
            resource_metadata=dict(action_def.metadata),
        )
        if not hint.sql_context.has_any_material():
            return None
        return hint.model_dump(mode="json")

    def _build_evidence_layers(
        self,
        *,
        available_resources: list[dict[str, Any]],
        recall_results: list[dict[str, Any]],
        template_version_candidates: list[dict[str, Any]],
        external_content_evidence: list[dict[str, Any]],
        skill_catalog_summaries: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        生成单轮上下文的显式证据分层说明。

        这份结构的目的不是驱动流程，而是把“哪些证据默认常驻 Prompt、
        哪些证据默认只以摘要进入 Prompt”变成显式元数据，便于：
        - PromptBuilder 对主脑解释当前证据视图
        - EvidenceBudgetManager 在预算裁剪时保持同一套语义边界
        - 后续继续扩展证据层时不再依赖隐含约定
        """

        return {
            "always_on": [
                {
                    "field": "flow_draft",
                    "reason": "当前任务草稿、已确认参数和待补问题属于主脑当前轮必读事实。",
                },
                {
                    "field": "available_resources",
                    "reason": "受控资源目录决定 execution_action 的合法选择边界。",
                    "total_items": len(available_resources),
                },
                {
                    "field": "ledger_snapshot",
                    "reason": "当前轮账本快照决定主脑看到的最近决策、观察与 pending 状态。",
                },
                {
                    "field": "compiled_dag_digest",
                    "reason": "编译产物摘要是模板沉淀链路的稳定证据，而不是自动推进器。",
                },
                {
                    "field": "template_draft_digest",
                    "reason": "模板草稿摘要是 publish 决策的核心证据。",
                },
                {
                    "field": "template_version_digest",
                    "reason": "模板版本摘要是复跑和复用判断的核心证据。",
                },
                {
                    "field": "content_trust_policy",
                    "reason": "外部内容可信度规则必须始终常驻，防止主脑把外部内容误当系统事实。",
                },
            ],
            "search_on_demand": [
                {
                    "field": "recall_results",
                    "reason": "历史 recall 是辅助参考，默认只注入有限摘要。",
                    "total_items": len(recall_results),
                },
                {
                    "field": "template_version_candidates",
                    "reason": "模板候选是检索证据，默认只注入前几条候选摘要。",
                    "total_items": len(template_version_candidates),
                },
                {
                    "field": "external_content_evidence",
                    "reason": "外部内容默认不可信，只允许以摘要进入 Prompt。",
                    "total_items": len(external_content_evidence),
                },
                {
                    "field": "skill_catalog_summaries",
                    "reason": "技能目录只提供能力参考，不应无上限堆进 Prompt。",
                    "total_items": len(skill_catalog_summaries),
                },
            ],
        }


class TerminationResolver:
    """
    `TerminationResolver`（终止收口器）。

    这个类负责把主脑输出的 terminate 决策统一转换成模式层最终返回结果，
    让 `DataMakeReActPattern`（造数 ReAct 主控模式）结尾逻辑保持稳定。
    """

    async def resolve(self, decision: Any) -> dict[str, Any]:
        """
        处理 `terminate`（终止）类型决策，并组装最终返回结果。
        """

        final_status = getattr(decision, "final_status", None) or "completed"
        final_message = getattr(decision, "final_message", None) or ""
        success = final_status not in {"failed", "cancelled"}

        return {
            "success": success,
            "status": final_status,
            "output": final_message,
            "final_message": final_message,
            "decision": decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else decision,
        }
