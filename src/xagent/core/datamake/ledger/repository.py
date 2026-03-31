"""
`Ledger Repository`（业务账本仓储）模块。

第一阶段这里先提供一个内存版 `LedgerRepository`（业务账本仓储），
目标不是一次把数据库持久化做满，而是先把“决策 -> 观察 -> 挂起工单 -> 恢复快照”
这条主链跑通。

后续即使切到数据库实现，这个类对上暴露的方法边界也尽量保持稳定：
- append_decision
- append_observation
- append_ticket
- resolve_ticket
- consume_*_reply
- build_runtime_snapshot
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from ..contracts.decision import NextActionDecision
from ..contracts.interaction import ApprovalTicket, InteractionTicket
from ..contracts.observation import ObservationEnvelope


class LedgerRepository:
    """
    `LedgerRepository`（业务账本仓储）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：业务事实留痕的主存储入口

    第一阶段实现说明：
    - 先使用内存结构保存 append-only 事件和当前挂起工单。
    - 这样可以尽快把主循环、交互回流、继续执行这条链跑通。
    - 之后如果切数据库，只要保留方法语义，主脑和下游层不用大改。
    """

    def __init__(self) -> None:
        # append-only 事实流。每个 task_id 都有一条独立账本序列。
        self._records_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)

        # 当前任务的挂起用户交互工单。
        self._pending_interactions: dict[str, InteractionTicket] = {}

        # 当前任务的挂起审批工单。
        self._pending_approvals: dict[str, ApprovalTicket] = {}

        # 当前任务的最新轮次编号，用于让主脑在下一轮生成新的 round_id。
        self._round_by_task: dict[str, int] = defaultdict(int)

    async def append(self, record: Any) -> None:
        """
        追加一条标准化账本记录。

        这个通用入口主要保留给需要直接写事实流的场景。
        日常建议优先用 `append_decision` / `append_observation` /
        `append_ticket` 这些显式方法，语义更清楚。
        """

        task_id = self._extract_task_id(record)
        self._records_by_task[task_id].append(self._normalize_record(record))

    async def append_decision(
        self,
        task_id: str,
        round_id: int,
        decision: NextActionDecision,
    ) -> None:
        """
        追加一条 `NextActionDecision`（下一动作决策）到账本。

        这条记录是后续回放“为什么本轮这么做”的基础证据。
        """

        self._round_by_task[task_id] = max(self._round_by_task[task_id], round_id)
        self._records_by_task[task_id].append(
            {
                "record_type": "decision",
                "task_id": task_id,
                "round_id": round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "decision": decision.model_dump(mode="json"),
            }
        )

    async def append_observation(
        self,
        task_id: str,
        round_id: int,
        observation: ObservationEnvelope,
    ) -> None:
        """
        追加一条 `ObservationEnvelope`（观察结果外壳）到账本。

        这是主脑进入下一轮时最关键的“回流证据”。
        """

        self._records_by_task[task_id].append(
            {
                "record_type": "observation",
                "task_id": task_id,
                "round_id": round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "observation": observation.model_dump(mode="json"),
            }
        )

    async def append_ticket(
        self,
        task_id: str,
        round_id: int,
        ticket: InteractionTicket | ApprovalTicket,
    ) -> None:
        """
        追加一条挂起工单到账本，并同步更新当前挂起索引。

        这里的“挂起工单”包括：
        - `InteractionTicket`（用户交互工单）
        - `ApprovalTicket`（审批工单）
        """

        record_type = "interaction_ticket"
        if isinstance(ticket, ApprovalTicket):
            record_type = "approval_ticket"
            self._pending_approvals[task_id] = ticket
        else:
            self._pending_interactions[task_id] = ticket

        self._records_by_task[task_id].append(
            {
                "record_type": record_type,
                "task_id": task_id,
                "round_id": round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket": ticket.model_dump(mode="json"),
            }
        )

    async def resolve_interaction_ticket(
        self,
        task_id: str,
        ticket: InteractionTicket,
    ) -> None:
        """
        标记用户交互工单已处理完成，并同步清理挂起索引。
        """

        self._pending_interactions.pop(task_id, None)
        self._records_by_task[task_id].append(
            {
                "record_type": "interaction_ticket_resolved",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket": ticket.model_dump(mode="json"),
            }
        )

    async def resolve_approval_ticket(
        self,
        task_id: str,
        ticket: ApprovalTicket,
    ) -> None:
        """
        标记审批工单已处理完成，并同步清理挂起索引。
        """

        self._pending_approvals.pop(task_id, None)
        self._records_by_task[task_id].append(
            {
                "record_type": "approval_ticket_resolved",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket": ticket.model_dump(mode="json"),
            }
        )

    async def consume_interaction_reply(
        self,
        task_id: str,
        ticket: InteractionTicket,
        observation: ObservationEnvelope,
    ) -> None:
        """
        原子消费一条用户交互回复。

        业务语义上，“交互工单已回答”与“回答结果回流为 observation”
        属于同一个状态跃迁，因此这里提供一个统一入口，避免上层把它拆成
        多次持久化动作。
        """

        self._pending_interactions.pop(task_id, None)
        self._records_by_task[task_id].append(
            {
                "record_type": "interaction_ticket_resolved",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket": ticket.model_dump(mode="json"),
            }
        )
        self._records_by_task[task_id].append(
            {
                "record_type": "observation",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "observation": observation.model_dump(mode="json"),
            }
        )

    async def consume_approval_reply(
        self,
        task_id: str,
        ticket: ApprovalTicket,
        observation: ObservationEnvelope,
    ) -> None:
        """
        原子消费一条审批回复。

        与交互回复同理，这里把：
        - 审批工单从 pending 变为 resolved
        - 审批结果回流为 supervision observation
        视为一次业务状态跃迁。
        """

        self._pending_approvals.pop(task_id, None)
        self._records_by_task[task_id].append(
            {
                "record_type": "approval_ticket_resolved",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "ticket": ticket.model_dump(mode="json"),
            }
        )
        self._records_by_task[task_id].append(
            {
                "record_type": "observation",
                "task_id": task_id,
                "round_id": ticket.round_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "observation": observation.model_dump(mode="json"),
            }
        )

    async def load_pending_interaction(
        self, task_id: str
    ) -> Optional[InteractionTicket]:
        """
        读取当前任务的挂起用户交互工单。
        """

        ticket = self._pending_interactions.get(task_id)
        return deepcopy(ticket) if ticket else None

    async def load_pending_approval(self, task_id: str) -> Optional[ApprovalTicket]:
        """
        读取当前任务的挂起审批工单。
        """

        ticket = self._pending_approvals.get(task_id)
        return deepcopy(ticket) if ticket else None

    async def build_runtime_snapshot(self, task_id: str) -> dict[str, Any]:
        """
        构建任务级 `Runtime Snapshot`（运行时快照）。

        当前版本返回：
        - 全量事实流副本
        - 最近一次决策
        - 最近一次 observation
        - 当前挂起工单
        - 当前下一轮编号
        """

        records = deepcopy(self._records_by_task.get(task_id, []))
        latest_decision = self._find_latest_record(records, "decision", "decision")
        latest_observation = self._find_latest_record(
            records, "observation", "observation"
        )

        return {
            "task_id": task_id,
            "records": records,
            "latest_decision": latest_decision,
            "latest_observation": latest_observation,
            "pending_interaction": (
                self._pending_interactions[task_id].model_dump(mode="json")
                if task_id in self._pending_interactions
                else None
            ),
            "pending_approval": (
                self._pending_approvals[task_id].model_dump(mode="json")
                if task_id in self._pending_approvals
                else None
            ),
            "next_round_id": self._round_by_task.get(task_id, 0) + 1,
        }

    async def list_records(self, task_id: str) -> list[dict[str, Any]]:
        """
        返回当前任务的账本事实流副本。
        """

        return deepcopy(self._records_by_task.get(task_id, []))

    def get_next_round_id(self, task_id: str) -> int:
        """
        获取当前任务下一轮应使用的 round_id。
        """

        return self._round_by_task.get(task_id, 0) + 1

    def _extract_task_id(self, record: Any) -> str:
        """
        从通用记录对象中提取 task_id。

        这里容忍传入 dict 或 pydantic model，方便最小闭环阶段快速接入。
        """

        if isinstance(record, dict):
            task_id = record.get("task_id")
            if task_id:
                return str(task_id)

        if hasattr(record, "task_id"):
            task_id = getattr(record, "task_id")
            if task_id:
                return str(task_id)

        raise ValueError("账本记录缺少 task_id，无法写入 LedgerRepository")

    def _normalize_record(self, record: Any) -> dict[str, Any]:
        """
        将传入记录归一化为 dict。
        """

        if isinstance(record, dict):
            return deepcopy(record)
        if hasattr(record, "model_dump"):
            return record.model_dump(mode="json")
        raise TypeError("LedgerRepository 仅支持 dict 或 pydantic model 记录")

    def _find_latest_record(
        self,
        records: list[dict[str, Any]],
        record_type: str,
        payload_key: str,
    ) -> Optional[dict[str, Any]]:
        """
        查找某类记录最近的一条有效载荷。
        """

        for record in reversed(records):
            if record.get("record_type") == record_type:
                return deepcopy(record.get(payload_key))
        return None


def create_persistent_ledger_repository(
    session_factory: Any,
    projection_updater: Any | None = None,
) -> Any:
    """
    创建持久化版 ledger repository。

    保持这个工厂放在 `repository.py`，让上层调用方仍然从统一入口拿仓储实现。
    """

    from .persistent_repository import PersistentLedgerRepository

    return PersistentLedgerRepository(
        session_factory=session_factory,
        projection_updater=projection_updater,
    )
