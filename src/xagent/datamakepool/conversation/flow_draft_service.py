"""FlowDraft 持久化服务。

职责：
- 为会话创建新 FlowDraft（同时 supersede 旧草稿）
- 更新 probe findings 和 readiness verdict
- 状态转换：draft -> probe_pending -> ready / superseded
- 把当前 active_flow_draft_id 写回 ConversationSession
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_conversation import DataMakepoolConversationSession
from xagent.web.models.datamakepool_flow_draft import DataMakepoolFlowDraft


class FlowDraftService:
    """FlowDraft 的 CRUD 与状态转换。"""

    def __init__(self, db: Session):
        self._db = db

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def create_draft(
        self,
        *,
        session_id: int,
        steps: list[dict[str, Any]],
        param_graph: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> DataMakepoolFlowDraft:
        """为会话创建新草稿，将旧 active draft 标记为 superseded。"""

        # 算下一个版本号
        latest = (
            self._db.query(DataMakepoolFlowDraft)
            .filter(DataMakepoolFlowDraft.session_id == session_id)
            .order_by(DataMakepoolFlowDraft.version.desc())
            .first()
        )
        next_version = (latest.version + 1) if latest else 1

        # supersede 所有非终态旧草稿
        self._db.query(DataMakepoolFlowDraft).filter(
            DataMakepoolFlowDraft.session_id == session_id,
            DataMakepoolFlowDraft.status.notin_(["superseded"]),
        ).update({"status": "superseded"}, synchronize_session=False)

        draft = DataMakepoolFlowDraft(
            session_id=session_id,
            version=next_version,
            status="draft",
            steps=steps,
            param_graph=param_graph,
            notes=notes,
        )
        self._db.add(draft)
        self._db.flush()  # 拿到 id 后再写回 session

        self._db.query(DataMakepoolConversationSession).filter(
            DataMakepoolConversationSession.id == session_id
        ).update(
            {"active_flow_draft_id": draft.id},
            synchronize_session="fetch",
        )
        self._db.commit()
        self._db.refresh(draft)
        return draft

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_active_draft(
        self, session_id: int
    ) -> DataMakepoolFlowDraft | None:
        """返回该会话当前 active 草稿（非 superseded 中版本最高的）。"""

        return (
            self._db.query(DataMakepoolFlowDraft)
            .filter(
                DataMakepoolFlowDraft.session_id == session_id,
                DataMakepoolFlowDraft.status.notin_(["superseded"]),
            )
            .order_by(DataMakepoolFlowDraft.version.desc())
            .first()
        )

    def get_draft_by_id(
        self, draft_id: int
    ) -> DataMakepoolFlowDraft | None:
        return (
            self._db.query(DataMakepoolFlowDraft)
            .filter(DataMakepoolFlowDraft.id == draft_id)
            .first()
        )

    # ------------------------------------------------------------------
    # 状态转换
    # ------------------------------------------------------------------

    def mark_probe_pending(self, draft_id: int) -> DataMakepoolFlowDraft | None:
        """draft -> probe_pending。"""

        return self._transition(draft_id, from_status="draft", to_status="probe_pending")

    def apply_probe_findings(
        self,
        draft_id: int,
        *,
        findings: list[dict[str, Any]],
    ) -> DataMakepoolFlowDraft | None:
        """追加 probe 发现，状态回到 draft（等待下一轮 readiness 判定）。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None
        existing = list(draft.probe_findings or [])
        existing.extend(findings)
        draft.probe_findings = existing
        draft.status = "draft"
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return draft

    def apply_readiness_verdict(
        self,
        draft_id: int,
        *,
        verdict: dict[str, Any],
    ) -> DataMakepoolFlowDraft | None:
        """写入 readiness gate 判定结果，若 ready=True 则状态升为 ready。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None
        draft.readiness_verdict = verdict
        draft.status = "ready" if verdict.get("ready") else "draft"
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return draft

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _transition(
        self,
        draft_id: int,
        *,
        from_status: str,
        to_status: str,
    ) -> DataMakepoolFlowDraft | None:
        draft = self.get_draft_by_id(draft_id)
        if draft is None or draft.status != from_status:
            return draft
        draft.status = to_status
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return draft
