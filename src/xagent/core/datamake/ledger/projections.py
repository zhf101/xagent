"""
`Projection`（投影）模块。

投影不是事实本身，而是为了查询方便，从账本事实派生出的当前状态视图。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .sql_models import DataMakeTaskProjection


class ProjectionUpdater:
    """
    `ProjectionUpdater`（投影更新器）。

    所属分层：
    - 代码分层：`ledger`
    - 需求分层：`Memory / Ledger Plane`（记忆 / 账本平面）
    - 在你的设计里：当前状态查询视图的刷新器

    主要职责：
    - 把 append-only 账本记录更新为便于查询的当前状态投影。
    - 例如任务状态投影、`FlowDraft`（流程草稿）当前视图、审批状态摘要等。
    - 让控制台、查询接口不需要每次全量回放账本。
    """

    def update(
        self,
        *,
        session: Session,
        task_id: str,
        round_id: int,
        record_type: str,
        payload_json: dict[str, Any],
    ) -> DataMakeTaskProjection:
        """
        根据账本记录刷新投影。

        这里更新的是派生视图，不应反向修改账本原始事实。
        """

        projection = self._get_or_create_projection(session, task_id)

        if record_type == "decision":
            projection.latest_decision_json = payload_json
        elif record_type == "observation":
            projection.latest_observation_json = payload_json
            status = payload_json.get("status")
            if isinstance(status, str) and status:
                projection.task_status = status
            elif projection.task_status in ("waiting_user", "waiting_human"):
                # observation 到达意味着等待态已经被消费，状态应回到 running
                projection.task_status = "running"
        elif record_type == "interaction_ticket":
            projection.pending_interaction_json = payload_json
            projection.task_status = "waiting_user"
        elif record_type == "approval_ticket":
            projection.pending_approval_json = payload_json
            projection.task_status = "waiting_human"
        elif record_type == "interaction_ticket_resolved":
            projection.pending_interaction_json = None
        elif record_type == "approval_ticket_resolved":
            projection.pending_approval_json = None

        projection.next_round_id = max(int(projection.next_round_id), round_id + 1)
        return projection

    def _get_or_create_projection(
        self,
        session: Session,
        task_id: str,
    ) -> DataMakeTaskProjection:
        projection = session.get(DataMakeTaskProjection, task_id)
        if projection is None:
            projection = DataMakeTaskProjection(task_id=task_id, next_round_id=1)
            session.add(projection)
            session.flush()
        return projection
