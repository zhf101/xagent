"""系统主数据、系统成员角色与环境地址映射模型。

这个模块只承载当前分支真正需要的三类数据：
1. `SystemRegistry`
   负责维护合法的 `system_short` 主数据，给 HTTP 资产、SQL 数据源、Vanna 知识库提供统一归属键。
2. `UserSystemRole`
   负责维护某个用户在某个系统下的角色，用于系统管理页展示和后续权限收口。
3. `SystemEnvironmentEndpoint`
   负责维护某个系统在不同环境标签下实际应该命中的 HTTP 基地址。

当前分支明确不启用审批流，因此这里不会引入审批请求、审批日志等额外表，
避免把无关复杂度带回当前代码线。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class SystemRegistry(Base):  # type: ignore
    """系统主数据表。

    业务上所有“系统归属”都应该落到 `system_short`，
    所以这里把它设计成自然主键，避免再引入一层仅数据库内部可见的 surrogate id。
    """

    __tablename__ = "system_registry"

    system_short = Column(
        String(64),
        primary_key=True,
        index=True,
        nullable=False,
        comment="系统唯一简称，统一使用大写格式",
    )
    display_name = Column(
        String(128),
        nullable=False,
        comment="系统中文/展示名称",
    )
    description = Column(
        Text,
        nullable=True,
        comment="系统说明，帮助新同学理解系统边界与用途",
    )
    status = Column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="系统状态：active/disabled",
    )
    created_by = Column(
        Integer,
        nullable=False,
        index=True,
        comment="创建人用户 ID。这里只记录数值，不绑定强外键，避免历史用户删除后反向阻塞主数据。",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    roles = relationship(
        "UserSystemRole",
        back_populates="system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    environment_endpoints = relationship(
        "SystemEnvironmentEndpoint",
        back_populates="system",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """统一提供接口层可直接返回的结构。

        这样 API 层只关注组合额外统计字段，不必重复手写基础序列化逻辑。
        """

        return {
            "system_short": self.system_short,
            "display_name": self.display_name,
            "description": self.description,
            "status": self.status,
            "created_by": int(self.created_by),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserSystemRole(Base):  # type: ignore
    """用户在某个系统下的角色绑定。

    当前只保留两种角色：
    - `member`：普通系统成员
    - `system_admin`：系统管理员

    这里的边界很明确：它只描述“用户属于哪个系统、在系统里是什么角色”，
    不承担审批节点、资源范围白名单等更复杂的职责。
    """

    __tablename__ = "user_system_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "system_short", name="uq_user_system_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="成员用户 ID",
    )
    system_short = Column(
        String(64),
        ForeignKey("system_registry.system_short", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属系统简称",
    )
    role = Column(
        String(32),
        nullable=False,
        index=True,
        comment="系统角色：member/system_admin",
    )
    granted_by = Column(
        Integer,
        nullable=False,
        index=True,
        comment="最近一次授予/更新该角色的操作者 ID",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    system = relationship("SystemRegistry", back_populates="roles")

    def to_dict(self) -> dict[str, Any]:
        """输出给前端成员列表的基础字段。"""

        return {
            "id": int(self.id),
            "user_id": int(self.user_id),
            "system_short": self.system_short,
            "role": self.role,
            "granted_by": int(self.granted_by),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SystemEnvironmentEndpoint(Base):  # type: ignore
    """系统环境地址映射。

    这张表解决的是 HTTP 资产 `url_mode=tag` 的落地问题：
    - 资产里只保存“这个接口属于哪个系统、命中哪个环境标签”
    - 真正的物理基地址统一沉淀在系统管理里维护

    这样同一系统下几十个 HTTP 资产都可以复用一套环境切换配置，
    避免每个资产各自写一份 `UAT/PROD` 地址，后续迁移或域名切换时难以统一收口。
    """

    __tablename__ = "system_environment_endpoints"
    __table_args__ = (
        UniqueConstraint(
            "system_short",
            "env_label",
            name="uq_system_environment_endpoint",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    system_short = Column(
        String(64),
        ForeignKey("system_registry.system_short", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属系统简称",
    )
    env_label = Column(
        String(64),
        nullable=False,
        index=True,
        comment="环境标签，例如 DEV/UAT/PROD/INTERNAL",
    )
    base_url = Column(
        Text,
        nullable=False,
        comment="该系统在当前环境标签下实际请求的 HTTP 基地址",
    )
    description = Column(
        Text,
        nullable=True,
        comment="环境说明，帮助调用方理解标签用途与网络边界",
    )
    status = Column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        comment="环境地址状态：active/disabled",
    )
    created_by = Column(
        Integer,
        nullable=False,
        index=True,
        comment="创建人用户 ID",
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    system = relationship("SystemRegistry", back_populates="environment_endpoints")

    def to_dict(self) -> dict[str, Any]:
        """输出给系统管理和 HTTP 资产表单使用的环境地址结构。"""

        return {
            "id": int(self.id),
            "system_short": self.system_short,
            "env_label": self.env_label,
            "base_url": self.base_url,
            "description": self.description,
            "status": self.status,
            "created_by": int(self.created_by),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
