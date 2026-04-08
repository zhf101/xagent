"""系统主数据、系统成员角色与环境地址映射 API。

当前分支没有审批功能，因此这个接口层坚持两条原则：
1. 系统管理只做直接 CRUD，不做申请/审批/驳回。
2. 系统主数据是“资产归属键”的基础设施，所有读写都优先追求简单和稳定。

页面侧主要有三类调用方：
- 系统管理页：管理员维护 system_short 和成员角色
- 数据源管理 / HTTP 资产页：读取 system options 供下拉选择
- HTTP 资产页：读取环境标签 options，并把 tag 模式真正落到基地址映射
- 未来其他治理页：复用同一套系统主数据
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.system_registry import (
    SystemEnvironmentEndpoint,
    SystemRegistry,
    UserSystemRole,
)
from ..models.user import User

router = APIRouter(tags=["system_registry"])

SYSTEM_STATUS_ACTIVE = "active"
SYSTEM_STATUS_DISABLED = "disabled"
SYSTEM_ROLE_MEMBER = "member"
SYSTEM_ROLE_ADMIN = "system_admin"
ENV_ENDPOINT_STATUS_ACTIVE = "active"
ENV_ENDPOINT_STATUS_DISABLED = "disabled"


def _normalize_system_short(value: str) -> str:
    """统一规范 system_short。

    这里强制转成大写，目的是避免前端有人录入 `crm/CRM/Crm` 产生多份主数据。
    """

    normalized = (value or "").strip().upper()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="system_short is required",
        )
    return normalized


def _require_global_admin(user: User) -> None:
    """只有全局管理员可以维护系统主数据与成员角色。"""

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


def _get_system_or_404(db: Session, system_short: str) -> SystemRegistry:
    """读取一条系统主数据，不存在则抛 404。"""

    normalized = _normalize_system_short(system_short)
    row = (
        db.query(SystemRegistry)
        .filter(SystemRegistry.system_short == normalized)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown system_short: {normalized}",
        )
    return row


def _serialize_system_with_counts(
    *,
    db: Session,
    row: SystemRegistry,
) -> dict[str, object]:
    """给系统列表补充成员统计。

    系统管理页需要同时展示成员数和系统管理员数，
    这里集中封装，避免每个路由重复拼接。
    """

    member_count = (
        db.query(UserSystemRole)
        .filter(UserSystemRole.system_short == row.system_short)
        .count()
    )
    system_admin_count = (
        db.query(UserSystemRole)
        .filter(
            UserSystemRole.system_short == row.system_short,
            UserSystemRole.role == SYSTEM_ROLE_ADMIN,
        )
        .count()
    )
    env_endpoint_count = (
        db.query(SystemEnvironmentEndpoint)
        .filter(SystemEnvironmentEndpoint.system_short == row.system_short)
        .count()
    )
    return {
        **row.to_dict(),
        "member_count": member_count,
        "system_admin_count": system_admin_count,
        "env_endpoint_count": env_endpoint_count,
    }


def _normalize_env_label(value: str) -> str:
    """统一规范环境标签。

    这里和 `system_short` 一样收口成大写，避免前端录入 `prod/PROD/Prod`
    导致同一环境被拆成多条配置。
    """

    normalized = (value or "").strip().upper()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="env_label is required",
        )
    return normalized


def _normalize_base_url(value: str) -> str:
    """规范环境标签对应的基础地址。

    这里不做复杂 URL 解析，只做两个关键收口：
    - 去前后空格
    - 去掉尾部 `/`，保证后续和 `url_suffix` 拼接时不会出现双斜杠
    """

    normalized = (value or "").strip().rstrip("/")
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="base_url is required",
        )
    return normalized


def _get_env_endpoint_or_404(
    db: Session,
    *,
    system_short: str,
    env_label: str,
) -> SystemEnvironmentEndpoint:
    """读取一条系统环境地址映射。"""

    normalized_system = _normalize_system_short(system_short)
    normalized_label = _normalize_env_label(env_label)
    row = (
        db.query(SystemEnvironmentEndpoint)
        .filter(
            SystemEnvironmentEndpoint.system_short == normalized_system,
            SystemEnvironmentEndpoint.env_label == normalized_label,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown env endpoint: {normalized_system}/{normalized_label}",
        )
    return row


class SystemRegistryCreateRequest(BaseModel):
    """创建系统主数据请求。"""

    system_short: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)


class SystemRegistryUpdateRequest(BaseModel):
    """更新系统主数据请求。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "disabled"] | None = None


class SystemMemberRoleRequest(BaseModel):
    """新增/更新系统成员角色请求。"""

    user_id: int = Field(..., ge=1)
    role: Literal["member", "system_admin"]


class SystemMemberRoleUpdateRequest(BaseModel):
    """单独更新成员角色请求。"""

    role: Literal["member", "system_admin"]


class SystemEnvironmentEndpointCreateRequest(BaseModel):
    """创建系统环境地址映射请求。"""

    env_label: str = Field(..., min_length=1, max_length=64)
    base_url: str = Field(..., min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)


class SystemEnvironmentEndpointUpdateRequest(BaseModel):
    """更新系统环境地址映射请求。"""

    base_url: str | None = Field(default=None, min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "disabled"] | None = None


@router.get("/api/system-registry/options")
def list_system_registry_options(
    include_system_short: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """返回系统下拉选项。

    设计重点：
    - 默认只返回 `active` 系统，避免新资产继续挂到停用系统上
    - 编辑历史资产时，如果它当前绑定的是 disabled 系统，允许通过 `include_system_short`
      把该条记录补回选项列表，保证页面仍可正确展示旧值
    """

    del user

    rows = {
        row.system_short: row
        for row in db.query(SystemRegistry)
        .filter(SystemRegistry.status == SYSTEM_STATUS_ACTIVE)
        .all()
    }

    if include_system_short:
        included = (
            db.query(SystemRegistry)
            .filter(
                SystemRegistry.system_short
                == _normalize_system_short(include_system_short)
            )
            .first()
        )
        if included is not None:
            rows[included.system_short] = included

    data = [
        {
            "system_short": row.system_short,
            "display_name": row.display_name,
            "description": row.description,
            "status": row.status,
        }
        for row in sorted(rows.values(), key=lambda item: item.system_short)
    ]
    return {"data": data}


@router.get("/api/system-registry/env-options")
def list_system_environment_options(
    system_short: str = Query(...),
    include_env_label: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """返回某个系统下可供 HTTP 资产选择的环境标签。

    设计约束：
    - 默认只暴露 `active` 环境，避免新资产继续选到停用地址
    - 编辑旧资产时，如果当前绑定标签已停用，允许通过 `include_env_label`
      补回当前值，保证历史记录仍可正确渲染和修改
    """

    del user

    normalized_system = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized_system)

    rows = {
        row.env_label: row
        for row in db.query(SystemEnvironmentEndpoint)
        .filter(
            SystemEnvironmentEndpoint.system_short == normalized_system,
            SystemEnvironmentEndpoint.status == ENV_ENDPOINT_STATUS_ACTIVE,
        )
        .all()
    }

    if include_env_label:
        included = (
            db.query(SystemEnvironmentEndpoint)
            .filter(
                SystemEnvironmentEndpoint.system_short == normalized_system,
                SystemEnvironmentEndpoint.env_label
                == _normalize_env_label(include_env_label),
            )
            .first()
        )
        if included is not None:
            rows[included.env_label] = included

    return {
        "data": [
            {
                "env_label": row.env_label,
                "base_url": row.base_url,
                "description": row.description,
                "status": row.status,
            }
            for row in sorted(rows.values(), key=lambda item: item.env_label)
        ]
    }


@router.get("/api/system-registry")
def list_system_registry(
    status_value: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """列出系统主数据。

    这是系统管理页的主列表接口，只允许管理员访问。
    """

    _require_global_admin(user)

    query = db.query(SystemRegistry)
    if status_value:
        query = query.filter(SystemRegistry.status == status_value)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            (SystemRegistry.system_short.ilike(pattern))
            | (SystemRegistry.display_name.ilike(pattern))
        )

    rows = query.order_by(SystemRegistry.system_short.asc()).all()
    return {
        "data": [
            _serialize_system_with_counts(db=db, row=row)
            for row in rows
        ]
    }


@router.post("/api/system-registry")
def create_system_registry_entry(
    payload: SystemRegistryCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """直接创建系统主数据。"""

    _require_global_admin(user)
    normalized = _normalize_system_short(payload.system_short)
    existing = (
        db.query(SystemRegistry)
        .filter(SystemRegistry.system_short == normalized)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"System {normalized} already exists",
        )

    row = SystemRegistry(
        system_short=normalized,
        display_name=payload.display_name.strip(),
        description=(payload.description or "").strip() or None,
        status=SYSTEM_STATUS_ACTIVE,
        created_by=int(user.id),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"data": _serialize_system_with_counts(db=db, row=row)}


@router.put("/api/system-registry/{system_short}")
def update_system_registry_entry(
    system_short: str,
    payload: SystemRegistryUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """直接更新系统主数据。"""

    _require_global_admin(user)
    row = _get_system_or_404(db, system_short)

    if payload.display_name is not None:
        row.display_name = payload.display_name.strip()
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.status is not None:
        row.status = payload.status

    db.commit()
    db.refresh(row)
    return {"data": _serialize_system_with_counts(db=db, row=row)}


@router.get("/api/system-registry/{system_short}/env-endpoints")
def list_system_environment_endpoints(
    system_short: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """列出某个系统下维护的环境地址映射。"""

    _require_global_admin(user)
    normalized = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized)

    rows = (
        db.query(SystemEnvironmentEndpoint)
        .filter(SystemEnvironmentEndpoint.system_short == normalized)
        .order_by(
            SystemEnvironmentEndpoint.env_label.asc(),
            SystemEnvironmentEndpoint.id.asc(),
        )
        .all()
    )
    return {"data": [row.to_dict() for row in rows]}


@router.post("/api/system-registry/{system_short}/env-endpoints")
def create_system_environment_endpoint(
    system_short: str,
    payload: SystemEnvironmentEndpointCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """给某个系统新增环境标签与基地址映射。"""

    _require_global_admin(user)
    normalized_system = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized_system)
    normalized_label = _normalize_env_label(payload.env_label)

    existing = (
        db.query(SystemEnvironmentEndpoint)
        .filter(
            SystemEnvironmentEndpoint.system_short == normalized_system,
            SystemEnvironmentEndpoint.env_label == normalized_label,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Env endpoint {normalized_system}/{normalized_label} already exists",
        )

    row = SystemEnvironmentEndpoint(
        system_short=normalized_system,
        env_label=normalized_label,
        base_url=_normalize_base_url(payload.base_url),
        description=(payload.description or "").strip() or None,
        status=ENV_ENDPOINT_STATUS_ACTIVE,
        created_by=int(user.id),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"data": row.to_dict()}


@router.put("/api/system-registry/{system_short}/env-endpoints/{env_label}")
def update_system_environment_endpoint(
    system_short: str,
    env_label: str,
    payload: SystemEnvironmentEndpointUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """更新环境标签对应的基础地址与状态。"""

    _require_global_admin(user)
    row = _get_env_endpoint_or_404(
        db,
        system_short=system_short,
        env_label=env_label,
    )

    if payload.base_url is not None:
        row.base_url = _normalize_base_url(payload.base_url)
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.status is not None:
        row.status = payload.status

    db.commit()
    db.refresh(row)
    return {"data": row.to_dict()}


@router.delete("/api/system-registry/{system_short}/env-endpoints/{env_label}")
def delete_system_environment_endpoint(
    system_short: str,
    env_label: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """删除某个系统下的环境标签地址映射。"""

    _require_global_admin(user)
    row = _get_env_endpoint_or_404(
        db,
        system_short=system_short,
        env_label=env_label,
    )
    db.delete(row)
    db.commit()
    return {"message": "removed"}


@router.get("/api/system-registry/{system_short}/members")
def list_system_registry_members(
    system_short: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, object]]]:
    """列出某个系统下的成员角色。"""

    _require_global_admin(user)
    normalized = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized)

    rows = (
        db.query(UserSystemRole, User)
        .join(User, User.id == UserSystemRole.user_id)
        .filter(UserSystemRole.system_short == normalized)
        .order_by(UserSystemRole.created_at.asc(), UserSystemRole.id.asc())
        .all()
    )
    return {
        "data": [
            {
                **role.to_dict(),
                "username": member.username,
            }
            for role, member in rows
        ]
    }


@router.post("/api/system-registry/{system_short}/members")
def create_system_registry_member(
    system_short: str,
    payload: SystemMemberRoleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """给某个系统新增成员角色。

    如果该用户已在当前系统下存在角色，则直接更新成新角色，
    这样前端不需要区分“新增”还是“覆盖”。
    """

    _require_global_admin(user)
    normalized = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized)

    member = db.query(User).filter(User.id == int(payload.user_id)).first()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    row = (
        db.query(UserSystemRole)
        .filter(
            UserSystemRole.user_id == int(payload.user_id),
            UserSystemRole.system_short == normalized,
        )
        .first()
    )
    if row is None:
        row = UserSystemRole(
            user_id=int(payload.user_id),
            system_short=normalized,
            role=payload.role,
            granted_by=int(user.id),
        )
        db.add(row)
    else:
        row.role = payload.role
        row.granted_by = int(user.id)

    db.commit()
    db.refresh(row)
    return {
        "data": {
            **row.to_dict(),
            "username": member.username,
        }
    }


@router.put("/api/system-registry/{system_short}/members/{user_id}")
def update_system_registry_member(
    system_short: str,
    user_id: int,
    payload: SystemMemberRoleUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, dict[str, object]]:
    """更新系统成员角色。

    这里复用和新增完全一致的语义，但保留独立路由，方便前端表达“修改角色”动作。
    """

    return create_system_registry_member(
        system_short=system_short,
        payload=SystemMemberRoleRequest(user_id=user_id, role=payload.role),
        db=db,
        user=user,
    )


@router.delete("/api/system-registry/{system_short}/members/{user_id}")
def delete_system_registry_member(
    system_short: str,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """移除系统成员角色。

    约束点：
    - 允许移除普通成员
    - 移除 `system_admin` 时，必须保证该系统仍然至少保留一名系统管理员
    """

    _require_global_admin(user)
    normalized = _normalize_system_short(system_short)
    _get_system_or_404(db, normalized)

    row = (
        db.query(UserSystemRole)
        .filter(
            UserSystemRole.user_id == int(user_id),
            UserSystemRole.system_short == normalized,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System role not found",
        )

    if row.role == SYSTEM_ROLE_ADMIN:
        remaining_admin_count = (
            db.query(UserSystemRole)
            .filter(
                UserSystemRole.system_short == normalized,
                UserSystemRole.role == SYSTEM_ROLE_ADMIN,
                UserSystemRole.user_id != int(user_id),
            )
            .count()
        )
        if remaining_admin_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one system_admin must remain",
            )

    db.delete(row)
    db.commit()
    return {"message": "removed"}
