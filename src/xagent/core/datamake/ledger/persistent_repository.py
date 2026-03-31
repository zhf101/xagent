"""
`Persistent Ledger Repository`（持久化账本仓储）模块。

这一层把 datamake 的 append-only 事实流与挂起状态持久化到数据库，
但不获得任何“下一步业务动作”的决策权。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional

from sqlalchemy.orm import Session, sessionmaker

from ..contracts.decision import NextActionDecision
from ..contracts.interaction import ApprovalTicket, InteractionTicket
from ..contracts.observation import ObservationEnvelope
from .projections import ProjectionUpdater
from .repository import LedgerRepository
from .sql_models import (
    DataMakeLedgerRecord,
    DataMakeTaskProjection,
)


class PersistentLedgerRepository(LedgerRepository):
    """
    `PersistentLedgerRepository`（持久化账本仓储）。

    对上保持与 `LedgerRepository` 一致的方法边界；
    对下把事实与当前态视图写到数据库。
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Callable[[], Session],
        projection_updater: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.projection_updater = projection_updater or ProjectionUpdater()

    async def append(self, record: Any) -> None:
        """
        追加一条标准化账本记录。
        """

        normalized = self._normalize_record(record)
        task_id = self._extract_task_id(normalized)
        round_id = int(normalized.get("round_id", 0))
        record_type = str(normalized["record_type"])
        payload_key, payload_json = self._extract_payload(record_type, normalized)
        created_at = normalized.get("created_at")

        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type=record_type,
                payload_json=payload_json,
                created_at=created_at,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type=record_type,
                payload_json=payload_json,
            )
            session.commit()

    async def append_decision(
        self,
        task_id: str,
        round_id: int,
        decision: NextActionDecision,
    ) -> None:
        payload = decision.model_dump(mode="json")
        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type="decision",
                payload_json=payload,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type="decision",
                payload_json=payload,
            )
            session.commit()

    async def append_observation(
        self,
        task_id: str,
        round_id: int,
        observation: ObservationEnvelope,
    ) -> None:
        payload = observation.model_dump(mode="json")
        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type="observation",
                payload_json=payload,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type="observation",
                payload_json=payload,
            )
            session.commit()

    async def append_ticket(
        self,
        task_id: str,
        round_id: int,
        ticket: InteractionTicket | ApprovalTicket,
    ) -> None:
        record_type = "approval_ticket" if isinstance(ticket, ApprovalTicket) else "interaction_ticket"
        payload = ticket.model_dump(mode="json")

        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type=record_type,
                payload_json=payload,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=round_id,
                record_type=record_type,
                payload_json=payload,
            )
            session.commit()

    async def resolve_interaction_ticket(
        self,
        task_id: str,
        ticket: InteractionTicket,
    ) -> None:
        payload = ticket.model_dump(mode="json")
        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=ticket.round_id,
                record_type="interaction_ticket_resolved",
                payload_json=payload,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=ticket.round_id,
                record_type="interaction_ticket_resolved",
                payload_json=payload,
            )
            session.commit()

    async def resolve_approval_ticket(
        self,
        task_id: str,
        ticket: ApprovalTicket,
    ) -> None:
        payload = ticket.model_dump(mode="json")
        with self._new_session() as session:
            self._insert_record(
                session=session,
                task_id=task_id,
                round_id=ticket.round_id,
                record_type="approval_ticket_resolved",
                payload_json=payload,
            )
            self._update_projection(
                session=session,
                task_id=task_id,
                round_id=ticket.round_id,
                record_type="approval_ticket_resolved",
                payload_json=payload,
            )
            session.commit()

    async def load_pending_interaction(
        self,
        task_id: str,
    ) -> Optional[InteractionTicket]:
        projection = self._load_projection(task_id)
        pending = projection.pending_interaction_json if projection else None
        if not pending:
            return None
        return InteractionTicket.model_validate(pending)

    async def load_pending_approval(self, task_id: str) -> Optional[ApprovalTicket]:
        projection = self._load_projection(task_id)
        pending = projection.pending_approval_json if projection else None
        if not pending:
            return None
        return ApprovalTicket.model_validate(pending)

    async def build_runtime_snapshot(self, task_id: str) -> dict[str, Any]:
        with self._new_session() as session:
            records = (
                session.query(DataMakeLedgerRecord)
                .filter(DataMakeLedgerRecord.task_id == task_id)
                .order_by(DataMakeLedgerRecord.id.asc())
                .all()
            )
            projection = self.projection_updater._get_or_create_projection(session, task_id)

            return {
                "task_id": task_id,
                "records": [self._record_to_dict(record) for record in records],
                "latest_decision": projection.latest_decision_json,
                "latest_observation": projection.latest_observation_json,
                "pending_interaction": projection.pending_interaction_json,
                "pending_approval": projection.pending_approval_json,
                "next_round_id": projection.next_round_id,
            }

    async def list_records(self, task_id: str) -> list[dict[str, Any]]:
        with self._new_session() as session:
            records = (
                session.query(DataMakeLedgerRecord)
                .filter(DataMakeLedgerRecord.task_id == task_id)
                .order_by(DataMakeLedgerRecord.id.asc())
                .all()
            )
            return [self._record_to_dict(record) for record in records]

    def get_next_round_id(self, task_id: str) -> int:
        projection = self._load_projection(task_id)
        if projection is None:
            return 1
        return int(projection.next_round_id)

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        """
        兼容 sessionmaker 和无参 session factory，并保证异常时自动 rollback。
        """

        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("PersistentLedgerRepository 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _insert_record(
        self,
        *,
        session: Session,
        task_id: str,
        round_id: int,
        record_type: str,
        payload_json: dict[str, Any],
        created_at: Any | None = None,
    ) -> None:
        record = DataMakeLedgerRecord(
            task_id=task_id,
            round_id=round_id,
            record_type=record_type,
            payload_json=payload_json,
        )
        if created_at is not None:
            record.created_at = created_at
        session.add(record)

    def _update_projection(
        self,
        *,
        session: Session,
        task_id: str,
        round_id: int,
        record_type: str,
        payload_json: dict[str, Any],
    ) -> None:
        self.projection_updater.update(
            session=session,
            task_id=task_id,
            round_id=round_id,
            record_type=record_type,
            payload_json=payload_json,
        )

    def _load_projection(self, task_id: str) -> DataMakeTaskProjection | None:
        with self._new_session() as session:
            projection = session.get(DataMakeTaskProjection, task_id)
            if projection is None:
                return None
            session.expunge(projection)
            return projection

    def _extract_payload(
        self,
        record_type: str,
        record: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if record_type == "decision":
            return "decision", dict(record["decision"])
        if record_type == "observation":
            return "observation", dict(record["observation"])
        if "ticket" in record and isinstance(record["ticket"], dict):
            return "ticket", dict(record["ticket"])
        raise ValueError(f"无法识别 record_type={record_type} 的 payload 结构")

    def _record_to_dict(self, record: DataMakeLedgerRecord) -> dict[str, Any]:
        payload_key = "payload"
        if record.record_type == "decision":
            payload_key = "decision"
        elif record.record_type == "observation":
            payload_key = "observation"
        elif "ticket" in record.record_type:
            payload_key = "ticket"

        return {
            "record_type": record.record_type,
            "task_id": record.task_id,
            "round_id": record.round_id,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            payload_key: record.payload_json,
        }
