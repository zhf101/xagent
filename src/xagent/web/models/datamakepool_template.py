"""Datamakepool 模板与版本模型。

模板层承载“可复用造数流程”的静态定义，核心思想是：
- `DataMakepoolTemplate` 管理模板身份、归属系统、当前发布版本
- `DataMakepoolTemplateVersion` 冻结某次发布时的执行步骤和参数契约

这样运行时可以只引用版本快照，避免模板后续编辑影响历史 Run 的可追溯性。
"""

import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class TemplateStatus(str, enum.Enum):
    """模板主记录状态。

    `ACTIVE` 表示模板可继续被匹配和执行；
    `DISABLED` 表示暂时下线但保留历史；
    `DELETED` 主要用于逻辑删除或后续治理扩展。
    """

    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


class DraftStatus(str, enum.Enum):
    """草稿流转状态。

    注意：草稿状态和模板主状态不是一回事。
    草稿关注“编辑/审核/发布流程”，模板主状态关注“已发布模板能否被运行时使用”。
    """

    EDITING = "editing"
    PENDING_PUBLISH = "pending_publish"
    PUBLISHED = "published"
    REJECTED = "rejected"


class DataMakepoolTemplate(Base):  # type: ignore
    """模板主表。

    这里只记录模板的长期身份信息，不直接保存执行步骤明细。
    真正用于执行的步骤定义会冻结在 `DataMakepoolTemplateVersion.step_spec_snapshot`。
    """

    __tablename__ = "datamakepool_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    # 模板归属系统；匹配时会优先拿它和用户输入中的 system_short 做对齐。
    system_short = Column(String(50), nullable=False, index=True)
    # 状态决定模板是否继续参与候选集，而不是草稿审核是否结束。
    status = Column(String(20), nullable=False, default=TemplateStatus.ACTIVE.value)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    # 某些模板可跨系统复用，因此单独保留适用系统列表。
    applicable_systems = Column(JSON, nullable=True)
    # 指向“当前对外生效”的版本号，运行时拿它去查快照。
    current_version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataMakepoolTemplateVersion(Base):  # type: ignore
    """模板发布版本快照。

    这是运行时最关键的契约表：
    - `step_spec_snapshot` 决定模板真正执行哪些步骤
    - `param_schema_snapshot` 决定调用方应提供哪些参数

    一旦发布，历史版本原则上不回写，以保证 Run 能回放到当时的定义。
    """

    __tablename__ = "datamakepool_template_versions"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=False
    )
    # 版本号和模板主表的 current_version 对应，显式存储便于直接查询。
    version = Column(Integer, nullable=False)
    # 执行步骤的冻结快照，是生成 RunStep 的权威来源。
    step_spec_snapshot = Column(JSON, nullable=False)
    # 参数契约快照，避免模板后续编辑影响已发布版本的入参语义。
    param_schema_snapshot = Column(JSON, nullable=True)
    published_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
