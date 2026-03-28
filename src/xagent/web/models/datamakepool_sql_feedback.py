"""Accepted SQL 回灌审计模型。

这张表专门记录“人工接受某条 SQL，并显式回灌到 SQL Brain 训练集”的动作。

为什么需要单独建表：
- `question_sql` 向量库只保存训练结果，不保存操作者和治理上下文
- accepted feedback 属于治理动作，后续需要回答“谁在什么时候喂了什么 SQL”
- 即使训练失败或被风险规则拒绝，也应该保留尝试记录，方便追查
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolSqlFeedback(Base):  # type: ignore
    """Accepted SQL 回灌账本。

    字段语义：
    - `question` / `accepted_sql`：用户确认的训练样本原文
    - `accepted_reason`：人工说明的口径、背景或确认原因
    - `allow_high_risk`：调用方是否显式允许高风险 SQL 进入训练
    - `requires_approval` / `approval_reason`：本次风险判定结果快照
    - `status`：回灌动作的最终状态，而不是 SQL 自身的业务状态
    - `train_result`：训练完成后的结构化返回，方便后续排查
    """

    __tablename__ = "datamakepool_sql_feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    system_short = Column(String(50), nullable=False, index=True)
    datasource_asset_id = Column(
        Integer, ForeignKey("datamakepool_assets.id"), nullable=True
    )
    db_type = Column(String(50), nullable=True)
    question = Column(Text, nullable=False)
    accepted_sql = Column(Text, nullable=False)
    accepted_reason = Column(Text, nullable=True)
    allow_high_risk = Column(Boolean, nullable=False, default=False)
    requires_approval = Column(Boolean, nullable=False, default=False)
    approval_reason = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    train_result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    accepted_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
