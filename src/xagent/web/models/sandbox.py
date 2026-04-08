"""Sandbox 宿主模型。

这里保存的是平台对 sandbox 实例的登记信息：
- 属于哪种 sandbox 类型
- 当前状态是什么
- 模板与运行配置是什么
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, func

from .database import Base


class SandboxInfo(Base):  # type: ignore[no-any-unimported]
    """Sandbox 实例登记表。

    关键字段说明：
    - `sandbox_type`: 当前用的是哪种实现，例如 boxlite/docker
    - `name`: 业务侧可识别的 sandbox 名称
    - `template`: sandbox 模板快照
    - `config`: sandbox 运行配置快照
    """

    __tablename__ = "sandbox_info"
    __table_args__ = (
        UniqueConstraint("name", "sandbox_type", name="uix_name_sandbox_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    sandbox_type = Column(
        String(50), nullable=False, index=True
    )  # boxlite, docker, etc.
    name = Column(String(255), nullable=False, index=True)
    state = Column(String(50), nullable=False)

    # Template stored as JSON
    template = Column(
        Text
    )  # JSON string: {"type": "...", "image": "...", "snapshot_id": "..."}

    # Config stored as JSON
    config = Column(
        Text
    )  # JSON string: {"cpus": ..., "memory": ..., "env": {...}, "volumes": [...], ...}

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
