"""
`Recovery`（恢复）模块。

这个模块处理的是长动作、暂停态、审批后续跑等 continuation 场景。
它保证流程可以断点续跑，而不是每次都从头来过。
"""

from __future__ import annotations

from typing import Any

from ..ledger.repository import LedgerRepository
from .resume_token import parse_resume_token


class RecoveryCoordinator:
    """
    `RecoveryCoordinator`（恢复协调器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：暂停 / 恢复控制器

    主要职责：
    - 协调 `pause`（暂停）/ `resume`（恢复）令牌。
    - 为长动作恢复、审批后 continuation、异常后重试恢复提供技术支持。
    - 保证恢复流程依赖标准化上下文，而不是隐式内存状态。
    """

    def __init__(self, ledger_repository: LedgerRepository) -> None:
        self.ledger_repository = ledger_repository

    async def resume(self, resume_token: Any) -> Any:
        """
        基于恢复信息继续执行。

        未来这里会读取 resume token 对应的账本或运行时状态，
        决定从哪个执行节点续跑。
        """

        token = parse_resume_token(resume_token)

        pending_interaction = await self.ledger_repository.load_pending_interaction(
            token.task_id
        )
        if pending_interaction is not None:
            return {
                "kind": "waiting_user",
                "task_id": token.task_id,
                "ticket": pending_interaction,
            }

        pending_approval = await self.ledger_repository.load_pending_approval(token.task_id)
        if pending_approval is not None:
            return {
                "kind": "waiting_human",
                "task_id": token.task_id,
                "ticket": pending_approval,
            }

        snapshot = await self.ledger_repository.build_runtime_snapshot(token.task_id)
        return {
            "kind": "no_pending",
            "task_id": token.task_id,
            "snapshot": snapshot,
        }
