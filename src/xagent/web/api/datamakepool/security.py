"""Datamakepool 治理权限校验辅助。

这一层专门服务 datamakepool 领域，不扩散到整个站点的全局权限模型。
目标是把“系统级治理权限”统一收口到：

1. 平台全局管理员 `users.is_admin`
2. 新的 `UserSystemBinding`
3. 旧 `DataMakepoolAdminBinding` 兼容回退

这样各个资产 / 模板 / 场景治理 API 不需要各自重复拼权限判断。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ....datamakepool.approvals import ApprovalService
from ...models.user import User


def ensure_system_governance_access(
    *,
    db: Session,
    user: User,
    system_short: str | None,
    required_role: str = "normal_admin",
) -> None:
    """校验当前用户是否具备某个业务系统的治理权限。

    适用范围：
    - datamakepool 资产增删改
    - 后续模板草稿审核、模板发布、审批处理等系统级治理动作
    """

    normalized_system = str(system_short or "").strip().lower()
    if not normalized_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="system_short is required for governance actions",
        )

    allowed = ApprovalService(db).user_has_approval_role(
        user_id=int(user.id),
        required_role=required_role,
        system_short=normalized_system,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Governance access denied for system '{normalized_system}', "
                f"required role: {required_role}"
            ),
        )


def ensure_global_governance_admin(*, user: User) -> None:
    """校验当前用户是否具备全局治理管理员权限。

    用于不落在单一 `system_short` 下的跨系统治理动作。
    当前先收敛为平台全局管理员，避免单系统管理员越权处理全局目录。
    """

    if not bool(user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global governance admin access required",
        )
