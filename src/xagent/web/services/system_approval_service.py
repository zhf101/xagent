"""System-centric asset approval service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ...core.database.types import DatabaseType, normalize_database_type
from ...core.database.config import clean_database_name
from ...core.gdp.http_asset_protocol import GdpHttpAssetStatus, GdpHttpAssetUpsertRequest
from ...core.gdp.http_asset_validator import GdpHttpAssetValidator
from ...core.vanna.index_service import IndexService
from ..models.gdp_http_resource import GdpHttpResource
from ..models.system_approval import (
    AssetChangeRequest,
    AssetChangeRequestLog,
    SystemRegistry,
    UserSystemRole,
)
from ..models.text2sql import DatabaseStatus, Text2SQLDatabase
from ..models.user import User
from ..models.vanna import (
    VannaTrainingEntry,
    VannaTrainingLifecycleStatus,
    VannaTrainingQualityStatus,
)

SYSTEM_ROLE_MEMBER = "member"
SYSTEM_ROLE_ADMIN = "system_admin"
SYSTEM_STATUS_ACTIVE = "active"
SYSTEM_STATUS_DISABLED = "disabled"
REQUEST_STATUS_DRAFT = "draft"
REQUEST_STATUS_PENDING = "pending_approval"
REQUEST_STATUS_APPROVED = "approved"
REQUEST_STATUS_REJECTED = "rejected"
REQUEST_STATUS_CANCELLED = "cancelled"
REQUEST_STATUS_SUPERSEDED = "superseded"
REQUEST_TYPE_CREATE = "create"
REQUEST_TYPE_UPDATE = "update"
REQUEST_TYPE_DELETE = "delete"
ASSET_TYPE_DATASOURCE = "datasource"
ASSET_TYPE_HTTP_RESOURCE = "http_resource"
ASSET_TYPE_TRAINING_ENTRY = "training_entry"
ACTIVE_LIFECYCLE_STATUS = "active"
ARCHIVED_LIFECYCLE_STATUS = "archived"


class SystemApprovalError(ValueError):
    """Business error for system approval workflows."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_system_short(value: str) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        raise SystemApprovalError("system_short is required")
    return normalized


def normalize_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped or None


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _serialize_training_entry(entry: VannaTrainingEntry) -> dict[str, Any]:
    return {
        "id": int(entry.id),
        "kb_id": int(entry.kb_id),
        "datasource_id": int(entry.datasource_id),
        "system_short": entry.system_short,
        "env": entry.env,
        "entry_code": entry.entry_code,
        "entry_type": entry.entry_type,
        "source_kind": entry.source_kind,
        "source_ref": entry.source_ref,
        "lifecycle_status": entry.lifecycle_status,
        "quality_status": entry.quality_status,
        "title": entry.title,
        "question_text": entry.question_text,
        "sql_text": entry.sql_text,
        "sql_explanation": entry.sql_explanation,
        "doc_text": entry.doc_text,
        "schema_name": entry.schema_name,
        "table_name": entry.table_name,
        "business_domain": entry.business_domain,
        "system_name": entry.system_name,
        "subject_area": entry.subject_area,
        "statement_kind": entry.statement_kind,
        "tables_read_json": list(entry.tables_read_json or []),
        "columns_read_json": list(entry.columns_read_json or []),
        "output_fields_json": list(entry.output_fields_json or []),
        "variables_json": list(entry.variables_json or []),
        "tags_json": list(entry.tags_json or []),
        "verification_result_json": dict(entry.verification_result_json or {}),
        "quality_score": entry.quality_score,
        "content_hash": entry.content_hash,
        "create_user_id": int(entry.create_user_id),
        "create_user_name": entry.create_user_name,
        "verified_by": entry.verified_by,
        "verified_at": _serialize_datetime(entry.verified_at),
        "created_at": _serialize_datetime(entry.created_at),
        "updated_at": _serialize_datetime(entry.updated_at),
    }


@dataclass
class ApprovalActor:
    user_id: int
    username: str | None
    is_admin: bool


class SystemApprovalService:
    """Coordinates system registry, role checks, and asset approval workflows."""

    def __init__(self, db: Session):
        self.db = db
        self.http_validator = GdpHttpAssetValidator()

    def to_actor(self, user: User) -> ApprovalActor:
        return ApprovalActor(
            user_id=int(user.id),
            username=getattr(user, "username", None),
            is_admin=bool(user.is_admin),
        )

    def is_global_admin(self, user: User | ApprovalActor) -> bool:
        return bool(user.is_admin)

    def has_system_role(self, *, user_id: int, system_short: str, role: str) -> bool:
        normalized = normalize_system_short(system_short)
        return (
            self.db.query(UserSystemRole)
            .filter(
                UserSystemRole.user_id == int(user_id),
                UserSystemRole.system_short == normalized,
                UserSystemRole.role == role,
            )
            .first()
            is not None
        )

    def can_approve_system_request(self, *, actor: ApprovalActor, system_short: str) -> bool:
        return actor.is_admin or self.has_system_role(
            user_id=actor.user_id,
            system_short=system_short,
            role=SYSTEM_ROLE_ADMIN,
        )

    def require_global_admin(self, actor: ApprovalActor) -> None:
        if not actor.is_admin:
            raise SystemApprovalError("Only global admin can perform this action")

    def get_system(self, system_short: str) -> SystemRegistry | None:
        normalized = normalize_system_short(system_short)
        return (
            self.db.query(SystemRegistry)
            .filter(SystemRegistry.system_short == normalized)
            .first()
        )

    def require_active_system(self, system_short: str) -> SystemRegistry:
        system = self.get_system(system_short)
        if system is None:
            raise SystemApprovalError(f"Unknown system_short: {system_short}")
        if system.status != SYSTEM_STATUS_ACTIVE:
            raise SystemApprovalError(f"System {system.system_short} is disabled")
        return system

    def require_active_or_disabled_system(self, system_short: str) -> SystemRegistry:
        system = self.get_system(system_short)
        if system is None:
            raise SystemApprovalError(f"Unknown system_short: {system_short}")
        return system

    def list_systems(self, *, status: str | None = None, keyword: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(SystemRegistry)
        if status:
            query = query.filter(SystemRegistry.status == status)
        if keyword:
            like_pattern = f"%{keyword.strip()}%"
            query = query.filter(
                (SystemRegistry.system_short.ilike(like_pattern))
                | (SystemRegistry.display_name.ilike(like_pattern))
            )
        systems = query.order_by(SystemRegistry.system_short.asc()).all()
        return [
            {
                **system.to_dict(),
                "member_count": self.db.query(UserSystemRole)
                .filter(UserSystemRole.system_short == system.system_short)
                .count(),
                "system_admin_count": self.db.query(UserSystemRole)
                .filter(
                    UserSystemRole.system_short == system.system_short,
                    UserSystemRole.role == SYSTEM_ROLE_ADMIN,
                )
                .count(),
            }
            for system in systems
        ]

    def list_system_options(
        self, *, include_system_short: str | None = None
    ) -> list[dict[str, Any]]:
        query = self.db.query(SystemRegistry).filter(
            SystemRegistry.status == SYSTEM_STATUS_ACTIVE
        )
        systems = {system.system_short: system for system in query.all()}

        if include_system_short:
            normalized = normalize_system_short(include_system_short)
            included = self.get_system(normalized)
            if included is not None:
                systems[included.system_short] = included

        return [
            {
                "system_short": system.system_short,
                "display_name": system.display_name,
                "description": system.description,
                "status": system.status,
            }
            for system in sorted(systems.values(), key=lambda item: item.system_short)
        ]

    def create_system(
        self,
        *,
        actor: ApprovalActor,
        system_short: str,
        display_name: str,
        description: str | None,
    ) -> SystemRegistry:
        self.require_global_admin(actor)
        normalized = normalize_system_short(system_short)
        existing = self.get_system(normalized)
        if existing is not None:
            raise SystemApprovalError(f"System {normalized} already exists")
        system = SystemRegistry(
            system_short=normalized,
            display_name=display_name.strip(),
            description=(description or "").strip() or None,
            status=SYSTEM_STATUS_ACTIVE,
            created_by=actor.user_id,
        )
        self.db.add(system)
        self.db.commit()
        self.db.refresh(system)
        return system

    def update_system(
        self,
        *,
        actor: ApprovalActor,
        system_short: str,
        display_name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> SystemRegistry:
        self.require_global_admin(actor)
        system = self.require_active_or_disabled_system(system_short)
        if display_name is not None:
            system.display_name = display_name.strip()
        if description is not None:
            system.description = description.strip() or None
        if status is not None:
            if status not in {SYSTEM_STATUS_ACTIVE, SYSTEM_STATUS_DISABLED}:
                raise SystemApprovalError("status must be active or disabled")
            system.status = status
        self.db.commit()
        self.db.refresh(system)
        return system

    def list_system_members(self, *, actor: ApprovalActor, system_short: str) -> list[dict[str, Any]]:
        self.require_global_admin(actor)
        normalized = normalize_system_short(system_short)
        rows = (
            self.db.query(UserSystemRole, User)
            .join(User, User.id == UserSystemRole.user_id)
            .filter(UserSystemRole.system_short == normalized)
            .order_by(UserSystemRole.created_at.asc(), UserSystemRole.id.asc())
            .all()
        )
        return [
            {
                **role.to_dict(),
                "username": user.username,
            }
            for role, user in rows
        ]

    def assign_system_role(
        self,
        *,
        actor: ApprovalActor,
        system_short: str,
        user_id: int,
        role: str,
    ) -> UserSystemRole:
        self.require_global_admin(actor)
        self.require_active_or_disabled_system(system_short)
        user = self.db.query(User).filter(User.id == int(user_id)).first()
        if user is None:
            raise SystemApprovalError("User not found")
        if role not in {SYSTEM_ROLE_MEMBER, SYSTEM_ROLE_ADMIN}:
            raise SystemApprovalError("role must be member or system_admin")
        normalized = normalize_system_short(system_short)
        existing = (
            self.db.query(UserSystemRole)
            .filter(
                UserSystemRole.user_id == int(user_id),
                UserSystemRole.system_short == normalized,
            )
            .first()
        )
        if existing is None:
            existing = UserSystemRole(
                user_id=int(user_id),
                system_short=normalized,
                role=role,
                granted_by=actor.user_id,
            )
            self.db.add(existing)
        else:
            existing.role = role
            existing.granted_by = actor.user_id
        self.db.commit()
        self.db.refresh(existing)
        return existing

    def remove_system_role(self, *, actor: ApprovalActor, system_short: str, user_id: int) -> None:
        self.require_global_admin(actor)
        normalized = normalize_system_short(system_short)
        row = (
            self.db.query(UserSystemRole)
            .filter(
                UserSystemRole.user_id == int(user_id),
                UserSystemRole.system_short == normalized,
            )
            .first()
        )
        if row is None:
            raise SystemApprovalError("System role not found")
        if row.role == SYSTEM_ROLE_ADMIN:
            remaining = (
                self.db.query(UserSystemRole)
                .filter(
                    UserSystemRole.system_short == normalized,
                    UserSystemRole.role == SYSTEM_ROLE_ADMIN,
                    UserSystemRole.user_id != int(user_id),
                )
                .count()
            )
            if remaining == 0:
                raise SystemApprovalError("At least one system_admin must remain")
        self.db.delete(row)
        self.db.commit()

    def list_requests_for_requester(
        self,
        *,
        actor: ApprovalActor,
        status: str | None = None,
        asset_type: str | None = None,
        system_short: str | None = None,
    ) -> list[AssetChangeRequest]:
        query = self.db.query(AssetChangeRequest).filter(
            AssetChangeRequest.requested_by == actor.user_id
        )
        if status:
            query = query.filter(AssetChangeRequest.status == status)
        if asset_type:
            query = query.filter(AssetChangeRequest.asset_type == asset_type)
        if system_short:
            query = query.filter(
                AssetChangeRequest.system_short == normalize_system_short(system_short)
            )
        return query.order_by(
            AssetChangeRequest.requested_at.desc(), AssetChangeRequest.id.desc()
        ).all()

    def list_approval_queue(
        self,
        *,
        actor: ApprovalActor,
        system_short: str | None = None,
        asset_type: str | None = None,
        status: str = REQUEST_STATUS_PENDING,
    ) -> list[AssetChangeRequest]:
        query = self.db.query(AssetChangeRequest).filter(AssetChangeRequest.status == status)
        if asset_type:
            query = query.filter(AssetChangeRequest.asset_type == asset_type)
        if system_short:
            normalized = normalize_system_short(system_short)
            query = query.filter(AssetChangeRequest.system_short == normalized)
            if not self.can_approve_system_request(actor=actor, system_short=normalized):
                raise SystemApprovalError("No permission to view this approval queue")
        elif not actor.is_admin:
            managed_systems = self._list_managed_systems(actor.user_id)
            if not managed_systems:
                return []
            query = query.filter(AssetChangeRequest.system_short.in_(managed_systems))
        return query.order_by(
            AssetChangeRequest.requested_at.asc(), AssetChangeRequest.id.asc()
        ).all()

    def get_request(self, request_id: int) -> AssetChangeRequest | None:
        return (
            self.db.query(AssetChangeRequest)
            .filter(AssetChangeRequest.id == int(request_id))
            .first()
        )

    def get_request_with_logs(self, request_id: int) -> AssetChangeRequest:
        request = self.get_request(request_id)
        if request is None:
            raise SystemApprovalError("Request not found")
        return request

    def can_view_request(self, *, actor: ApprovalActor, request: AssetChangeRequest) -> bool:
        if actor.is_admin:
            return True
        if request.requested_by == actor.user_id:
            return True
        return self.can_approve_system_request(
            actor=actor,
            system_short=request.system_short,
        )

    def create_asset_change_request(
        self,
        *,
        actor: ApprovalActor,
        request_type: str,
        asset_type: str,
        system_short: str,
        env: str | None,
        payload_snapshot: dict[str, Any],
        asset_id: int | None = None,
        current_snapshot: dict[str, Any] | None = None,
        current_version_marker: str | None = None,
        change_summary: str | None = None,
        status: str = REQUEST_STATUS_PENDING,
    ) -> AssetChangeRequest:
        self.require_active_system(system_short)
        request = AssetChangeRequest(
            request_type=request_type,
            asset_type=asset_type,
            asset_id=str(asset_id) if asset_id is not None else None,
            system_short=normalize_system_short(system_short),
            env=normalize_env(env),
            status=status,
            requested_by=actor.user_id,
            submitted_at=utcnow() if status == REQUEST_STATUS_PENDING else None,
            change_summary=(change_summary or "").strip() or None,
            current_version_marker=current_version_marker,
            current_snapshot=current_snapshot or {},
            payload_snapshot=payload_snapshot or {},
        )
        self.db.add(request)
        self.db.flush()
        self._add_request_log(
            request=request,
            action="submitted" if status == REQUEST_STATUS_PENDING else "draft_saved",
            actor=actor,
            comment=change_summary,
            snapshot=request.to_dict(),
        )
        self.db.commit()
        self.db.refresh(request)
        return request

    def cancel_request(self, *, actor: ApprovalActor, request_id: int) -> AssetChangeRequest:
        request = self.get_request_with_logs(request_id)
        if request.requested_by != actor.user_id:
            raise SystemApprovalError("Only requester can cancel request")
        if request.status != REQUEST_STATUS_PENDING:
            raise SystemApprovalError("Only pending requests can be cancelled")
        request.status = REQUEST_STATUS_CANCELLED
        self._apply_training_entry_terminal_state(
            request=request,
            lifecycle_status=VannaTrainingLifecycleStatus.ARCHIVED.value,
            quality_status=VannaTrainingQualityStatus.UNVERIFIED.value,
        )
        self._add_request_log(
            request=request,
            action="cancelled",
            actor=actor,
            comment="request cancelled",
            snapshot=request.to_dict(),
        )
        self.db.commit()
        self.db.refresh(request)
        return request

    def approve_request(
        self, *, actor: ApprovalActor, request_id: int, comment: str | None = None
    ) -> AssetChangeRequest:
        request = self.get_request_with_logs(request_id)
        if request.status != REQUEST_STATUS_PENDING:
            raise SystemApprovalError("Only pending requests can be approved")
        if not self.can_approve_system_request(
            actor=actor, system_short=request.system_short
        ):
            raise SystemApprovalError("No permission to approve this request")

        current_asset = self._load_asset_for_request(request)
        if request.request_type in {REQUEST_TYPE_UPDATE, REQUEST_TYPE_DELETE}:
            if current_asset is None:
                request.status = REQUEST_STATUS_SUPERSEDED
                self._add_request_log(
                    request=request,
                    action="superseded",
                    actor=actor,
                    comment="asset no longer exists",
                    snapshot=request.to_dict(),
                )
                self.db.commit()
                self.db.refresh(request)
                return request
            latest_marker = self._build_version_marker(current_asset)
            if request.current_version_marker and request.current_version_marker != latest_marker:
                request.status = REQUEST_STATUS_SUPERSEDED
                self._add_request_log(
                    request=request,
                    action="superseded",
                    actor=actor,
                    comment="asset version changed before approval",
                    snapshot=request.to_dict(),
                )
                self.db.commit()
                self.db.refresh(request)
                return request

        applied_asset = self._project_request(
            request=request,
            current_asset=current_asset,
            approver=actor,
        )
        request.status = REQUEST_STATUS_APPROVED
        request.approved_by = actor.user_id
        request.approved_at = utcnow()
        request.approval_comment = (comment or "").strip() or None
        self._add_request_log(
            request=request,
            action="approved",
            actor=actor,
            comment=request.approval_comment or "approved",
            snapshot=request.to_dict(),
        )
        self.db.commit()
        if applied_asset is not None:
            self.db.refresh(applied_asset)
        self.db.refresh(request)
        return request

    def reject_request(
        self, *, actor: ApprovalActor, request_id: int, reason: str | None = None
    ) -> AssetChangeRequest:
        request = self.get_request_with_logs(request_id)
        if request.status != REQUEST_STATUS_PENDING:
            raise SystemApprovalError("Only pending requests can be rejected")
        if not self.can_approve_system_request(
            actor=actor, system_short=request.system_short
        ):
            raise SystemApprovalError("No permission to reject this request")
        request.status = REQUEST_STATUS_REJECTED
        self._apply_training_entry_terminal_state(
            request=request,
            lifecycle_status=VannaTrainingLifecycleStatus.ARCHIVED.value,
            quality_status=VannaTrainingQualityStatus.REJECTED.value,
        )
        request.rejected_by = actor.user_id
        request.rejected_at = utcnow()
        request.reject_reason = (reason or "").strip() or None
        self._add_request_log(
            request=request,
            action="rejected",
            actor=actor,
            comment=request.reject_reason or "rejected",
            snapshot=request.to_dict(),
        )
        self.db.commit()
        self.db.refresh(request)
        return request

    def serialize_request(self, request: AssetChangeRequest) -> dict[str, Any]:
        return {
            **request.to_dict(),
            "logs": [
                log.to_dict()
                for log in sorted(
                    request.logs,
                    key=lambda item: (
                        item.created_at or utcnow(),
                        item.id or 0,
                    ),
                )
            ],
        }

    def serialize_request_list(self, requests: Iterable[AssetChangeRequest]) -> list[dict[str, Any]]:
        return [request.to_dict() for request in requests]

    def submit_datasource_request(
        self,
        *,
        actor: ApprovalActor,
        payload: dict[str, Any],
        existing: Text2SQLDatabase | None = None,
        request_type: str,
    ) -> AssetChangeRequest:
        system_short = normalize_system_short(str(payload.get("system_short") or ""))
        env = normalize_env(payload.get("env"))
        if request_type in {REQUEST_TYPE_UPDATE, REQUEST_TYPE_DELETE} and existing is None:
            raise SystemApprovalError("Datasource not found")
        if request_type == REQUEST_TYPE_DELETE:
            payload_snapshot: dict[str, Any] = {}
        else:
            payload_snapshot = {
                "name": str(payload.get("name") or "").strip(),
                "system_short": system_short,
                "database_name": clean_database_name(payload.get("database_name")),
                "env": env,
                "type": str(payload.get("type") or "").strip(),
                "url": payload.get("url"),
                "connection_mode": payload.get("connection_mode"),
                "connection_form": payload.get("connection_form") or {},
                "read_only": bool(payload.get("read_only", True)),
            }
        return self.create_asset_change_request(
            actor=actor,
            request_type=request_type,
            asset_type=ASSET_TYPE_DATASOURCE,
            system_short=system_short if request_type != REQUEST_TYPE_DELETE else existing.system_short,
            env=env if request_type != REQUEST_TYPE_DELETE else existing.env,
            payload_snapshot=payload_snapshot,
            asset_id=int(existing.id) if existing is not None else None,
            current_snapshot=existing.to_dict() if existing is not None else {},
            current_version_marker=self._build_version_marker(existing) if existing is not None else None,
            change_summary=self._build_change_summary(
                asset_type=ASSET_TYPE_DATASOURCE,
                request_type=request_type,
                system_short=system_short if request_type != REQUEST_TYPE_DELETE else existing.system_short,
                env=env if request_type != REQUEST_TYPE_DELETE else existing.env,
                display_name=(payload_snapshot.get("name") or (existing.name if existing is not None else None)),
            ),
        )

    def submit_http_request(
        self,
        *,
        actor: ApprovalActor,
        payload: GdpHttpAssetUpsertRequest | None,
        existing: GdpHttpResource | None = None,
        request_type: str,
    ) -> AssetChangeRequest:
        if request_type in {REQUEST_TYPE_UPDATE, REQUEST_TYPE_DELETE} and existing is None:
            raise SystemApprovalError("HTTP asset not found")
        if request_type == REQUEST_TYPE_DELETE:
            system_short = normalize_system_short(existing.system_short)
            tool_name = existing.tool_name
            payload_snapshot: dict[str, Any] = {}
        else:
            if payload is None:
                raise SystemApprovalError("HTTP request payload is required")
            self.http_validator.validate(payload)
            system_short = normalize_system_short(payload.resource.system_short)
            tool_name = payload.tool_contract.tool_name
            payload_snapshot = payload.model_dump(mode="json")
        return self.create_asset_change_request(
            actor=actor,
            request_type=request_type,
            asset_type=ASSET_TYPE_HTTP_RESOURCE,
            system_short=system_short if request_type != REQUEST_TYPE_DELETE else existing.system_short,
            env=None,
            payload_snapshot=payload_snapshot,
            asset_id=int(existing.id) if existing is not None else None,
            current_snapshot=existing.to_detail_dict() if existing is not None else {},
            current_version_marker=self._build_version_marker(existing) if existing is not None else None,
            change_summary=self._build_change_summary(
                asset_type=ASSET_TYPE_HTTP_RESOURCE,
                request_type=request_type,
                system_short=system_short if request_type != REQUEST_TYPE_DELETE else existing.system_short,
                env=None,
                display_name=tool_name,
            ),
        )

    def submit_training_entry_request(
        self,
        *,
        actor: ApprovalActor,
        entry: VannaTrainingEntry,
        request_type: str = REQUEST_TYPE_CREATE,
    ) -> AssetChangeRequest:
        if request_type != REQUEST_TYPE_CREATE:
            raise SystemApprovalError("Training entries currently support create requests only")
        if not entry.id:
            raise SystemApprovalError("Training entry must be persisted before approval submission")
        return self.create_asset_change_request(
            actor=actor,
            request_type=request_type,
            asset_type=ASSET_TYPE_TRAINING_ENTRY,
            system_short=entry.system_short,
            env=entry.env,
            payload_snapshot=_serialize_training_entry(entry),
            asset_id=int(entry.id),
            current_snapshot=_serialize_training_entry(entry),
            current_version_marker=self._build_version_marker(entry),
            change_summary=self._build_change_summary(
                asset_type=ASSET_TYPE_TRAINING_ENTRY,
                request_type=request_type,
                system_short=entry.system_short,
                env=entry.env,
                display_name=entry.title or entry.entry_code,
            ),
        )

    def _list_managed_systems(self, user_id: int) -> list[str]:
        rows = (
            self.db.query(UserSystemRole.system_short)
            .filter(
                UserSystemRole.user_id == int(user_id),
                UserSystemRole.role == SYSTEM_ROLE_ADMIN,
            )
            .all()
        )
        return [row[0] for row in rows]

    def _add_request_log(
        self,
        *,
        request: AssetChangeRequest,
        action: str,
        actor: ApprovalActor,
        comment: str | None,
        snapshot: dict[str, Any] | None,
    ) -> None:
        self.db.add(
            AssetChangeRequestLog(
                request_id=int(request.id),
                action=action,
                operator_user_id=actor.user_id,
                operator_role=self._resolve_operator_role(actor, request.system_short),
                comment=(comment or "").strip() or None,
                snapshot=snapshot or {},
            )
        )

    def _resolve_operator_role(self, actor: ApprovalActor, system_short: str) -> str:
        if actor.is_admin:
            return "admin"
        if self.has_system_role(
            user_id=actor.user_id,
            system_short=system_short,
            role=SYSTEM_ROLE_ADMIN,
        ):
            return SYSTEM_ROLE_ADMIN
        if self.has_system_role(
            user_id=actor.user_id,
            system_short=system_short,
            role=SYSTEM_ROLE_MEMBER,
        ):
            return SYSTEM_ROLE_MEMBER
        return "user"

    def _load_asset_for_request(self, request: AssetChangeRequest) -> Any | None:
        if request.asset_type == ASSET_TYPE_DATASOURCE:
            if request.asset_id is None:
                return None
            return (
                self.db.query(Text2SQLDatabase)
                .filter(Text2SQLDatabase.id == int(request.asset_id))
                .first()
            )
        if request.asset_type == ASSET_TYPE_HTTP_RESOURCE:
            if request.asset_id is None:
                return None
            return (
                self.db.query(GdpHttpResource)
                .filter(GdpHttpResource.id == int(request.asset_id))
                .first()
            )
        if request.asset_type == ASSET_TYPE_TRAINING_ENTRY:
            if request.asset_id is None:
                return None
            return (
                self.db.query(VannaTrainingEntry)
                .filter(VannaTrainingEntry.id == int(request.asset_id))
                .first()
            )
        raise SystemApprovalError(f"Unsupported asset_type: {request.asset_type}")

    def _project_request(
        self,
        *,
        request: AssetChangeRequest,
        current_asset: Any | None,
        approver: ApprovalActor,
    ) -> Any | None:
        if request.asset_type == ASSET_TYPE_DATASOURCE:
            return self._project_datasource_request(
                request=request,
                current_asset=current_asset,
                approver=approver,
            )
        if request.asset_type == ASSET_TYPE_HTTP_RESOURCE:
            return self._project_http_request(
                request=request,
                current_asset=current_asset,
                approver=approver,
            )
        if request.asset_type == ASSET_TYPE_TRAINING_ENTRY:
            return self._project_training_entry_request(
                request=request,
                current_asset=current_asset,
                approver=approver,
            )
        raise SystemApprovalError(f"Unsupported asset_type: {request.asset_type}")

    def _project_datasource_request(
        self,
        *,
        request: AssetChangeRequest,
        current_asset: Text2SQLDatabase | None,
        approver: ApprovalActor,
    ) -> Text2SQLDatabase | None:
        payload = request.payload_snapshot or {}
        approval_time = utcnow()
        if request.request_type == REQUEST_TYPE_CREATE:
            row = Text2SQLDatabase(
                user_id=request.requested_by,
                name=str(payload["name"]),
                system_short=normalize_system_short(str(payload["system_short"])),
                database_name=clean_database_name(payload.get("database_name")),
                env=normalize_env(payload.get("env")) or "prod",
                type=DatabaseType(normalize_database_type(str(payload["type"]))),
                url=str(payload["url"]),
                read_only=bool(payload.get("read_only", True)),
                status=DatabaseStatus.DISCONNECTED,
                table_count=None,
                last_connected_at=None,
                lifecycle_status=ACTIVE_LIFECYCLE_STATUS,
                approval_request_id=int(request.id),
                approved_by=approver.user_id,
                approved_at=approval_time,
                updated_by=request.requested_by,
            )
            self.db.add(row)
            self.db.flush()
            return row

        if current_asset is None:
            raise SystemApprovalError("Datasource not found during projection")

        if request.request_type == REQUEST_TYPE_DELETE:
            current_asset.lifecycle_status = ARCHIVED_LIFECYCLE_STATUS
            current_asset.approval_request_id = int(request.id)
            current_asset.approved_by = approver.user_id
            current_asset.approved_at = approval_time
            current_asset.updated_by = approver.user_id
            return current_asset

        current_asset.name = str(payload["name"])
        current_asset.system_short = normalize_system_short(str(payload["system_short"]))
        current_asset.database_name = clean_database_name(payload.get("database_name"))
        current_asset.env = normalize_env(payload.get("env")) or current_asset.env
        current_asset.type = DatabaseType(normalize_database_type(str(payload["type"])))
        current_asset.url = str(payload["url"])
        current_asset.read_only = bool(payload.get("read_only", True))
        current_asset.status = DatabaseStatus.DISCONNECTED
        current_asset.table_count = None
        current_asset.last_connected_at = None
        current_asset.error_message = None
        current_asset.approval_request_id = int(request.id)
        current_asset.approved_by = approver.user_id
        current_asset.approved_at = approval_time
        current_asset.updated_by = request.requested_by
        current_asset.lifecycle_status = ACTIVE_LIFECYCLE_STATUS
        return current_asset

    def _project_http_request(
        self,
        *,
        request: AssetChangeRequest,
        current_asset: GdpHttpResource | None,
        approver: ApprovalActor,
    ) -> GdpHttpResource | None:
        approval_time = utcnow()
        payload = (
            GdpHttpAssetUpsertRequest.model_validate(request.payload_snapshot)
            if request.request_type != REQUEST_TYPE_DELETE
            else None
        )
        if request.request_type == REQUEST_TYPE_CREATE:
            assert payload is not None
            row = GdpHttpResource(
                resource_key=payload.resource.resource_key,
                system_short=normalize_system_short(payload.resource.system_short),
                create_user_id=request.requested_by,
                create_user_name=self._lookup_username(request.requested_by),
                visibility=payload.resource.visibility,
                status=int(GdpHttpAssetStatus.ACTIVE),
                summary=payload.resource.summary,
                tags_json=payload.resource.tags_json,
                tool_name=payload.tool_contract.tool_name,
                tool_description=payload.tool_contract.tool_description,
                input_schema_json=payload.tool_contract.input_schema_json,
                output_schema_json=payload.tool_contract.output_schema_json,
                annotations_json=payload.tool_contract.annotations_json,
                method=payload.execution_profile.method,
                url_mode=payload.execution_profile.url_mode,
                direct_url=payload.execution_profile.direct_url,
                sys_label=payload.execution_profile.sys_label,
                url_suffix=payload.execution_profile.url_suffix,
                args_position_json=payload.execution_profile.args_position_json,
                request_template_json=payload.execution_profile.request_template_json,
                response_template_json=payload.execution_profile.response_template_json,
                error_response_template=payload.execution_profile.error_response_template,
                auth_json=payload.execution_profile.auth_json,
                headers_json=payload.execution_profile.headers_json,
                timeout_seconds=payload.execution_profile.timeout_seconds,
                approval_request_id=int(request.id),
                approved_by=approver.user_id,
                approved_at=approval_time,
                updated_by=request.requested_by,
            )
            self.db.add(row)
            self.db.flush()
            return row

        if current_asset is None:
            raise SystemApprovalError("HTTP asset not found during projection")

        if request.request_type == REQUEST_TYPE_DELETE:
            current_asset.status = int(GdpHttpAssetStatus.DELETED)
            current_asset.approval_request_id = int(request.id)
            current_asset.approved_by = approver.user_id
            current_asset.approved_at = approval_time
            current_asset.updated_by = approver.user_id
            return current_asset

        assert payload is not None
        current_asset.resource_key = payload.resource.resource_key
        current_asset.system_short = normalize_system_short(payload.resource.system_short)
        current_asset.visibility = payload.resource.visibility
        current_asset.summary = payload.resource.summary
        current_asset.tags_json = payload.resource.tags_json
        current_asset.tool_name = payload.tool_contract.tool_name
        current_asset.tool_description = payload.tool_contract.tool_description
        current_asset.input_schema_json = payload.tool_contract.input_schema_json
        current_asset.output_schema_json = payload.tool_contract.output_schema_json
        current_asset.annotations_json = payload.tool_contract.annotations_json
        current_asset.method = payload.execution_profile.method
        current_asset.url_mode = payload.execution_profile.url_mode
        current_asset.direct_url = payload.execution_profile.direct_url
        current_asset.sys_label = payload.execution_profile.sys_label
        current_asset.url_suffix = payload.execution_profile.url_suffix
        current_asset.args_position_json = payload.execution_profile.args_position_json
        current_asset.request_template_json = payload.execution_profile.request_template_json
        current_asset.response_template_json = payload.execution_profile.response_template_json
        current_asset.error_response_template = payload.execution_profile.error_response_template
        current_asset.auth_json = payload.execution_profile.auth_json
        current_asset.headers_json = payload.execution_profile.headers_json
        current_asset.timeout_seconds = payload.execution_profile.timeout_seconds
        current_asset.approval_request_id = int(request.id)
        current_asset.approved_by = approver.user_id
        current_asset.approved_at = approval_time
        current_asset.updated_by = request.requested_by
        current_asset.status = int(GdpHttpAssetStatus.ACTIVE)
        return current_asset

    def _lookup_username(self, user_id: int) -> str | None:
        user = self.db.query(User).filter(User.id == int(user_id)).first()
        return getattr(user, "username", None)

    def _apply_training_entry_terminal_state(
        self,
        *,
        request: AssetChangeRequest,
        lifecycle_status: str,
        quality_status: str,
    ) -> None:
        if request.asset_type != ASSET_TYPE_TRAINING_ENTRY or request.asset_id is None:
            return
        entry = (
            self.db.query(VannaTrainingEntry)
            .filter(VannaTrainingEntry.id == int(request.asset_id))
            .first()
        )
        if entry is None:
            return
        entry.lifecycle_status = lifecycle_status
        entry.quality_status = quality_status
        IndexService(self.db).reindex_entry(entry_id=int(entry.id))

    def _project_training_entry_request(
        self,
        *,
        request: AssetChangeRequest,
        current_asset: VannaTrainingEntry | None,
        approver: ApprovalActor,
    ) -> VannaTrainingEntry:
        if request.request_type != REQUEST_TYPE_CREATE:
            raise SystemApprovalError("Unsupported training entry request type")

        payload = request.payload_snapshot or {}
        approval_time = utcnow().replace(tzinfo=None)
        entry = current_asset
        if entry is None:
            entry = self.db.query(VannaTrainingEntry).filter(
                VannaTrainingEntry.entry_code == str(payload.get("entry_code") or "")
            ).first()

        if entry is None:
            entry = VannaTrainingEntry(
                kb_id=int(payload["kb_id"]),
                datasource_id=int(payload["datasource_id"]),
                system_short=str(payload["system_short"]),
                env=str(payload["env"]),
                entry_code=str(payload["entry_code"]),
                entry_type=str(payload["entry_type"]),
                source_kind=payload.get("source_kind"),
                source_ref=payload.get("source_ref"),
                create_user_id=int(payload["create_user_id"]),
                create_user_name=payload.get("create_user_name"),
            )
            self.db.add(entry)
            self.db.flush()

        for field_name in (
            "title",
            "question_text",
            "sql_text",
            "sql_explanation",
            "doc_text",
            "schema_name",
            "table_name",
            "business_domain",
            "system_name",
            "subject_area",
            "statement_kind",
            "content_hash",
            "source_kind",
            "source_ref",
        ):
            setattr(entry, field_name, payload.get(field_name))

        entry.tables_read_json = list(payload.get("tables_read_json") or [])
        entry.columns_read_json = list(payload.get("columns_read_json") or [])
        entry.output_fields_json = list(payload.get("output_fields_json") or [])
        entry.variables_json = list(payload.get("variables_json") or [])
        entry.tags_json = list(payload.get("tags_json") or [])
        entry.verification_result_json = dict(payload.get("verification_result_json") or {})
        entry.quality_score = payload.get("quality_score")
        entry.lifecycle_status = VannaTrainingLifecycleStatus.PUBLISHED.value
        entry.quality_status = VannaTrainingQualityStatus.VERIFIED.value
        entry.verified_by = self._lookup_username(approver.user_id)
        entry.verified_at = approval_time
        self.db.flush()
        IndexService(self.db).reindex_entry(entry_id=int(entry.id))
        return entry

    def _build_version_marker(self, asset: Any | None) -> str | None:
        if asset is None:
            return None
        updated_at = getattr(asset, "updated_at", None)
        return _serialize_datetime(updated_at) or str(getattr(asset, "id", ""))

    def _build_change_summary(
        self,
        *,
        asset_type: str,
        request_type: str,
        system_short: str,
        env: str | None,
        display_name: str | None,
    ) -> str:
        target = display_name or asset_type
        scope = f"{system_short}/{env}" if env else system_short
        return f"{request_type} {asset_type} {target} @ {scope}"


__all__ = [
    "ASSET_TYPE_DATASOURCE",
    "ASSET_TYPE_HTTP_RESOURCE",
    "ASSET_TYPE_TRAINING_ENTRY",
    "ApprovalActor",
    "REQUEST_STATUS_APPROVED",
    "REQUEST_STATUS_PENDING",
    "REQUEST_STATUS_REJECTED",
    "REQUEST_STATUS_SUPERSEDED",
    "REQUEST_TYPE_CREATE",
    "REQUEST_TYPE_DELETE",
    "REQUEST_TYPE_UPDATE",
    "SYSTEM_ROLE_ADMIN",
    "SYSTEM_ROLE_MEMBER",
    "SystemApprovalError",
    "SystemApprovalService",
    "normalize_system_short",
]
