"""Datamakepool 审批单服务。

当前服务已经从“只会落审批单”演进为一个轻量审批领域服务：
- 创建审批单持久化记录
- 统一解析审批资格与系统治理权限

这样可以保证审批入口、候选人解析、系统绑定迁移都收口在同一处，
避免后续在 websocket / API / agent 侧各自复制权限判断逻辑。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_approval import (
    ApprovalStatus,
    DataMakepoolApproval,
)
from xagent.web.models.biz_system import BizSystem
from xagent.web.models.datamakepool_admin_binding import DataMakepoolAdminBinding
from xagent.web.models.user import User, UserSystemBinding


ROLE_RANK = {
    "member": 0,
    "normal_admin": 1,
    "system_admin": 2,
}


class ApprovalService:
    """审批与治理权限服务。

    这层现在同时承担两类领域职责：
    - 审批单创建：把运行时审批请求稳定落库
    - 审批资格判断：统一从 `users.is_admin`、`UserSystemBinding`、旧
      `DataMakepoolAdminBinding` 三层来源解析“谁有资格审批/治理”

    设计约束：
    - `UserSystemBinding` 是新的主模型，后续审批和系统治理都应优先使用它
    - `DataMakepoolAdminBinding` 只作为兼容回退，避免老数据在迁移期间失效
    """

    def __init__(self, db: Session):
        self._db = db

    def user_has_approval_role(
        self,
        *,
        user_id: int,
        required_role: str,
        system_short: str | None = None,
    ) -> bool:
        """判断某个用户是否具备审批资格。

        规则按优先级依次收口：
        1. 平台全局管理员 `users.is_admin=true` 直接拥有所有系统审批资格
        2. `UserSystemBinding` 作为新的正式绑定模型，负责系统维度授权
        3. 旧 `DataMakepoolAdminBinding` 仅作为灰度迁移兼容回退

        角色继承关系：
        - `system_admin` 覆盖 `normal_admin`
        - `normal_admin` 覆盖 `member`
        """

        user = self._db.query(User).filter(User.id == user_id).first()
        if user is None:
            return False

        if bool(user.is_admin):
            return True

        required_rank = ROLE_RANK.get(required_role, ROLE_RANK["system_admin"])
        binding_roles = self._load_user_system_binding_roles(
            user_id=user_id,
            system_short=system_short,
        )
        if any(ROLE_RANK.get(role, -1) >= required_rank for role in binding_roles):
            return True

        legacy_roles = self._load_legacy_binding_roles(
            user_id=user_id,
            system_short=system_short,
        )
        return any(ROLE_RANK.get(role, -1) >= required_rank for role in legacy_roles)

    def list_approver_user_ids(
        self,
        *,
        required_role: str,
        system_short: str | None = None,
    ) -> list[int]:
        """列出当前审批要求下可审批的用户 ID。

        该方法给审批单后续流转、通知分发、候选人展示提供统一入口。
        当前返回用户 ID 即可，避免在 service 层提前耦合展示文案。
        """

        user_ids: set[int] = {
            int(user_id)
            for (user_id,) in self._db.query(User.id).filter(User.is_admin.is_(True)).all()
        }

        has_user_system_bindings = self._table_exists("user_system_bindings") and self._table_exists(
            "biz_systems"
        )
        has_legacy_bindings = self._table_exists("datamakepool_admin_bindings")

        for role in self._expand_allowed_roles(required_role):
            if has_user_system_bindings:
                query = (
                    self._db.query(UserSystemBinding.user_id)
                    .join(BizSystem, BizSystem.id == UserSystemBinding.system_id)
                    .filter(
                        UserSystemBinding.is_active.is_(True),
                        UserSystemBinding.binding_role == role,
                    )
                )
                if system_short:
                    query = query.filter(BizSystem.system_short == system_short)
                user_ids.update(int(user_id) for (user_id,) in query.all())

            if has_legacy_bindings:
                legacy_query = self._db.query(DataMakepoolAdminBinding.user_id).filter(
                    DataMakepoolAdminBinding.role == role
                )
                if system_short:
                    legacy_query = legacy_query.filter(
                        DataMakepoolAdminBinding.system_short == system_short
                    )
                user_ids.update(int(user_id) for (user_id,) in legacy_query.all())

        return sorted(user_ids)

    def create_approval(
        self,
        approval_type: str,
        target_type: str,
        target_id: int,
        *,
        system_short: str | None = None,
        required_role: str | None = None,
        requester_id: int | None = None,
        context_data: dict[str, Any] | None = None,
    ) -> DataMakepoolApproval:
        """创建一张待审批单并立即 flush。

        输入语义：
        - `approval_type` / `target_type` / `target_id` 用于标识审批对象
        - `required_role` 表示审批人资格，而不是当前审批人
        - `context_data` 保存触发审批时的运行态上下文快照

        状态影响：
        - 会新增一条 `DataMakepoolApproval`
        - 会执行 `flush` 以便调用方立即拿到 `approval.id`
        - 不在这里 `commit`，事务边界由上层调用方控制
        """

        approval = DataMakepoolApproval(
            approval_type=approval_type,
            target_type=target_type,
            target_id=target_id,
            system_short=system_short,
            required_role=required_role,
            requester_id=requester_id,
            context_data=context_data,
            status=ApprovalStatus.PENDING.value,
        )
        self._db.add(approval)
        self._db.flush()
        return approval

    def _load_user_system_binding_roles(
        self,
        *,
        user_id: int,
        system_short: str | None,
    ) -> list[str]:
        """从新模型里读取用户在指定系统上的绑定角色。"""

        if not self._table_exists("user_system_bindings") or not self._table_exists(
            "biz_systems"
        ):
            return []

        query = (
            self._db.query(UserSystemBinding.binding_role)
            .join(BizSystem, BizSystem.id == UserSystemBinding.system_id)
            .filter(
                UserSystemBinding.user_id == user_id,
                UserSystemBinding.is_active.is_(True),
            )
        )
        if system_short:
            query = query.filter(BizSystem.system_short == system_short)
        return [str(role) for (role,) in query.all()]

    def _load_legacy_binding_roles(
        self,
        *,
        user_id: int,
        system_short: str | None,
    ) -> list[str]:
        """兼容读取旧 `DataMakepoolAdminBinding` 里的角色。

        迁移期内保留这层回退，保证未搬迁数据也还能走审批。
        """

        if not self._table_exists("datamakepool_admin_bindings"):
            return []

        query = self._db.query(DataMakepoolAdminBinding.role).filter(
            DataMakepoolAdminBinding.user_id == user_id
        )
        if system_short:
            query = query.filter(DataMakepoolAdminBinding.system_short == system_short)
        return [str(role) for (role,) in query.all()]

    @staticmethod
    def _expand_allowed_roles(required_role: str) -> Iterable[str]:
        """把目标角色展开成“满足该权限要求的所有角色集合”。"""

        required_rank = ROLE_RANK.get(required_role, ROLE_RANK["system_admin"])
        return [
            role
            for role, rank in ROLE_RANK.items()
            if rank >= required_rank
        ]

    def _table_exists(self, table_name: str) -> bool:
        """判断当前数据库里是否存在某张表。

        兼容轻量测试库或迁移未完整落地的场景，避免权限服务因为缺表直接抛 500。
        """

        bind = self._db.get_bind()
        inspector = inspect(bind)
        return table_name in inspector.get_table_names()
