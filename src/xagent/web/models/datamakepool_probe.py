"""智能造数平台 Probe 运行记录。

Probe 的职责不是完成正式造数，而是：
1. 验证局部假设
2. 探测真实结构或错误
3. 把结果回流给会话决策层
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolProbeRun(Base):  # type: ignore
    """局部试跑记录。"""

    __tablename__ = "datamakepool_probe_runs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    probe_type = Column(String(32), nullable=False, index=True)
    target_ref = Column(String(255), nullable=False, index=True)
    mode = Column(String(32), nullable=False, default="preview")
    success = Column(String(16), nullable=False, default="unknown", index=True)
    input_payload = Column(JSON, nullable=True)
    raw_result = Column(JSON, nullable=True)
    findings = Column(JSON, nullable=True)
    result_summary = Column(Text, nullable=True)
    user_visible_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
