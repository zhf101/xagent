"""Datamakepool 模板草稿模型。

草稿层用于承接“从任务沉淀模板”或“人工编辑模板”的中间态，
避免还未审核通过的定义直接污染正式模板与版本表。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolTemplateDraft(Base):  # type: ignore
    """模板草稿表。

    设计边界：
    - 草稿可以先独立存在，未必已经绑定正式模板，因此 `template_id` 允许为空
    - 草稿保存的是“可编辑状态”，发布时应再冻结成版本快照
    """

    __tablename__ = "datamakepool_template_drafts"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(
        Integer, ForeignKey("datamakepool_templates.id"), nullable=True
    )
    name = Column(String(200), nullable=False)
    system_short = Column(String(50), nullable=False, index=True)
    # 草稿状态描述审核/编辑流程，不参与运行时模板匹配。
    status = Column(String(20), nullable=False, default="pending_review")
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)
    applicable_systems = Column(JSON, nullable=True)
    # 可编辑步骤定义；审核通过后会被复制到版本表的 snapshot 字段中。
    step_spec = Column(JSON, nullable=True)
    # 草稿阶段的参数契约定义，发布时同步冻结为版本快照。
    param_schema = Column(JSON, nullable=True)
    # 记录草稿来源任务，便于回溯“哪次任务沉淀出这个模板”。
    source_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
