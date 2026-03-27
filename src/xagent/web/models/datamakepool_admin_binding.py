"""Datamakepool 管理员绑定模型。

该表把平台用户与业务系统管理权限绑定起来，
用于限制“谁可以管理某个 system_short 下的资产、模板与审批”。
"""

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolAdminBinding(Base):  # type: ignore
    """系统管理员绑定表。

    它不是通用 RBAC，而是 datamakepool 领域内的轻量授权收口点。
    """

    __tablename__ = "datamakepool_admin_bindings"

    id = Column(Integer, primary_key=True, index=True)
    # 用户 ID 对应平台用户；与 system_short 组合后表示管理边界。
    user_id = Column(Integer, nullable=False, index=True)
    # 被授权管理的业务系统。
    system_short = Column(String(50), nullable=False, index=True)
    # 当前先保留简单角色字符串，后续如需扩展更细粒度权限再演进。
    role = Column(String(30), nullable=False, default="normal_admin")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
