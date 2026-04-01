"""
`Flow Draft Sync`（流程草稿同步协调）模块。

这个模块负责把运行期 `context.state["flow_draft"]` 同步回
结构化 `FlowDraftAggregate` 宿主。

它存在的原因不是新增一层抽象，而是把 Pattern 里原本那段：
- 读取临时 flow_draft
- 合并已持久化版本
- 校验成 `FlowDraftState`
- 写入 aggregate 宿主
- 再把 projection 回写到 context.state

这一整段“宿主同步桥接”挪到 application 层，避免入口壳继续直接操心
draft service / aggregate service 的细节。
"""

from __future__ import annotations

from ...agent.context import AgentContext
from ..services.draft_service import DraftService
from ..services.flow_draft_aggregate_service import FlowDraftAggregateService
from ..services.models import FlowDraftState


class FlowDraftSyncCoordinator:
    """
    `FlowDraftSyncCoordinator`（流程草稿同步协调器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 Pattern/Runner 与 draft 宿主 service 之间

    职责边界：
    - 只负责把当前轮临时 `flow_draft` 同步回结构化持久化宿主
    - 同步完成后把规范化 projection 回写到 `context.state`

    明确不负责：
    - 不决定主脑下一步动作
    - 不修改 draft 领域模型语义
    - 不推动模板编译 / 发布 / 执行链路
    """

    def __init__(
        self,
        *,
        draft_service: DraftService | None,
        flow_draft_aggregate_service: FlowDraftAggregateService | None,
    ) -> None:
        self.draft_service = draft_service
        self.flow_draft_aggregate_service = flow_draft_aggregate_service

    async def persist_if_present(self, context: AgentContext) -> None:
        """
        若当前上下文携带了临时 `flow_draft`，则把它吸收到结构化 aggregate 宿主。

        关键约束：
        - 只有在同时具备 `DraftService` 与 `FlowDraftAggregateService` 时才执行
        - 只在 `context.state["flow_draft"]` 为 dict 时同步
        - 持久化成功后必须把 projection 回写到 `context.state`，
          避免后续 round context 继续消费一份未规范化的临时 JSON
        """

        if self.draft_service is None or self.flow_draft_aggregate_service is None:
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

        normalized_state = FlowDraftState.model_validate(draft_payload)
        aggregate = await self.flow_draft_aggregate_service.upsert_from_state(
            draft_state=normalized_state
        )
        context.state["flow_draft"] = self.draft_service.projection_service.to_state(
            aggregate
        ).model_dump(mode="json")
