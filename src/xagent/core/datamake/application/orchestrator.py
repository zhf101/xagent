"""
应用编排辅助模块。

这里放的是顶层主脑的“辅助编排器”，不是第二个主脑。
当前阶段最重要的职责，是把散落在 `context.state`、Recall、Ledger 中的信息
收敛成一份稳定的 `Round Context`（单轮上下文）。
"""

from __future__ import annotations

from typing import Any, Optional

from ...agent.context import AgentContext
from ..ledger.snapshots import SnapshotBuilder
from ..services.draft_service import DraftService
from ..services.recall_service import RecallService


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
    ) -> None:
        self.snapshot_builder = snapshot_builder
        self.recall_service = recall_service
        self.draft_service = draft_service

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

        flow_draft = dict(persisted_draft)
        state_draft = context.state.get("flow_draft")
        if isinstance(state_draft, dict):
            flow_draft.update(state_draft)

        return {
            "task_id": context.task_id,
            "session_id": context.session_id,
            "task": task,
            "user_id": context.user_id,
            "system_prompt": context.state.get("system_prompt"),
            "flow_draft": flow_draft,
            "context_state": context.state,
            "history": list(context.history),
            "recall_results": recall_results,
            "ledger_snapshot": ledger_snapshot,
            "file_info": context.state.get("file_info"),
            "uploaded_files": context.state.get("uploaded_files"),
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
