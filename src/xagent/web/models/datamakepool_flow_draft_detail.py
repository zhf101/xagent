"""智能造数平台 FlowDraft 子实体模型。

这些子表负责把原本堆在 FlowDraft 主表 JSON 里的结构拆开：

- DataMakepoolFlowDraftStep：草稿中的可执行步骤定义
- DataMakepoolFlowDraftParam：步骤需要消费或产出的参数状态
- DataMakepoolFlowDraftMapping：步骤输入与参数/上游输出之间的映射关系

设计目标：
- 让 probe/readiness/compile 不再只能围绕 JSON 粗粒度工作
- 让“哪个参数还缺、哪个映射断了、哪个步骤被阻塞”可以直接查询和审计
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolFlowDraftStep(Base):  # type: ignore
    """FlowDraft 中的单个步骤定义。

    step_key 是草稿内稳定主键，后续 probe、mapping、compiler 都围绕它工作。
    """

    __tablename__ = "datamakepool_flow_draft_steps"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(
        Integer,
        ForeignKey("datamakepool_flow_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key = Column(String(128), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    executor_type = Column(String(64), nullable=False, index=True)
    target_ref = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    step_order = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="drafting", index=True)
    dependencies = Column(JSON, nullable=True)
    config_payload = Column(JSON, nullable=True)
    output_contract = Column(JSON, nullable=True)
    blocking_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    draft = relationship("DataMakepoolFlowDraft", back_populates="step_rows")


class DataMakepoolFlowDraftParam(Base):  # type: ignore
    """FlowDraft 里的参数状态账本。

    status 关注的是“这个参数当前是否足够支撑下一步”：
    - pending：还没有值，或值还没经过 probe/映射验证
    - ready：已经有稳定值，可直接进入 compiler / execute
    - blocked：已经确认当前值不可用，必须补信息或修订映射
    """

    __tablename__ = "datamakepool_flow_draft_params"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(
        Integer,
        ForeignKey("datamakepool_flow_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    param_key = Column(String(128), nullable=False, index=True)
    label = Column(String(255), nullable=True)
    value_payload = Column(JSON, nullable=True)
    source_type = Column(String(32), nullable=False, default="session_fact", index=True)
    required = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="pending", index=True)
    blocking_reason = Column(Text, nullable=True)
    source_ref = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    draft = relationship("DataMakepoolFlowDraft", back_populates="param_rows")


class DataMakepoolFlowDraftMapping(Base):  # type: ignore
    """FlowDraft 中的输入映射关系。

    这张表负责表达：
    - 某一步骤的某个输入字段
    - 来自哪个参数、哪个上游步骤输出，或某个字面量
    - 当前映射是否已经闭合
    """

    __tablename__ = "datamakepool_flow_draft_mappings"

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(
        Integer,
        ForeignKey("datamakepool_flow_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_step_key = Column(String(128), nullable=False, index=True)
    target_field = Column(String(128), nullable=False)
    source_kind = Column(String(32), nullable=False, default="draft_param", index=True)
    source_ref = Column(String(255), nullable=True)
    source_path = Column(String(255), nullable=True)
    literal_value = Column(JSON, nullable=True)
    required = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="pending", index=True)
    blocking_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    draft = relationship("DataMakepoolFlowDraft", back_populates="mapping_rows")
