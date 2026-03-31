"""
`Replay`（回放）模块。

回放能力用于恢复、审计、排障和行为解释。
当需要知道“系统为什么会走到这一步”时，这一层很关键。
"""

from __future__ import annotations

from typing import Any

from .repository import LedgerRepository


class LedgerReplayService:
    """
    `LedgerReplayService`（账本回放服务）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：历史轨迹重建器

    主要职责：
    - 回放历史决策与 `observation`（观察结果）记录。
    - 为恢复、审计、调试、事故复盘提供支持。
    - 帮助解释流程的因果链，而不只是展示最后状态。
    """

    def __init__(self, ledger_repository: LedgerRepository) -> None:
        self.ledger_repository = ledger_repository

    async def replay(self, task_id: str) -> dict[str, Any]:
        """
        回放一个任务的账本历史。

        未来可输出时间线、事件序列，或供恢复逻辑消费的重建结果。
        """
        snapshot = await self.ledger_repository.build_runtime_snapshot(task_id)
        records = list(snapshot.get("records", []))

        return {
            "task_id": task_id,
            "records": records,
            "latest_decision": snapshot.get("latest_decision"),
            "latest_observation": snapshot.get("latest_observation"),
            "pending_interaction": snapshot.get("pending_interaction"),
            "pending_approval": snapshot.get("pending_approval"),
            "causal_summary": self._build_causal_summary(records),
        }

    def _build_causal_summary(self, records: list[dict[str, Any]]) -> list[str]:
        """
        生成最小可读因果链摘要。

        这里只解释“发生了什么”，不推导“下一步应该做什么”。
        """

        summary: list[str] = []
        for record in records:
            record_type = str(record.get("record_type", "unknown"))
            round_id = record.get("round_id")

            if record_type == "decision":
                decision = record.get("decision", {})
                summary.append(
                    f"round {round_id}: decision -> "
                    f"{decision.get('decision_mode')} / {decision.get('action_kind')} / {decision.get('action')}"
                )
            elif record_type == "observation":
                observation = record.get("observation", {})
                summary.append(
                    f"round {round_id}: observation -> "
                    f"{observation.get('observation_type')} / {observation.get('status')}"
                )
            elif "ticket" in record_type:
                ticket = record.get("ticket", {})
                summary.append(
                    f"round {round_id}: {record_type} -> "
                    f"{ticket.get('action')} / {ticket.get('status')}"
                )
            else:
                summary.append(f"round {round_id}: {record_type}")

        return summary
