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
from ..services.draft_service import DraftService
from ..services.recall_service import RecallService

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
    ) -> None:
        self.snapshot_builder = snapshot_builder
        self.recall_service = recall_service
        self.draft_service = draft_service
        self.resource_catalog = resource_catalog

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
        persisted_draft: dict[str, Any] = {}

        if self.recall_service is not None:
            recall_results = await self.recall_service.search(task)
        if self.draft_service is not None:
            loaded_draft = await self.draft_service.load(context.task_id)
            if loaded_draft is not None:
                persisted_draft = loaded_draft.model_dump(mode="json")

        # flow_draft 以持久化版本为基础，context.state 里的临时覆盖优先级更高。
        flow_draft = dict(persisted_draft)
        state_draft = context.state.get("flow_draft")
        if isinstance(state_draft, dict):
            flow_draft.update(state_draft)

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
            "ledger_snapshot": ledger_snapshot,
            "file_info": context.state.get("file_info"),
            "uploaded_files": context.state.get("uploaded_files"),
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
