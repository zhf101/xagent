"""智能造数平台 Probe 运行记录。

Probe 的职责不是完成正式造数，而是：
1. 验证局部假设
2. 探测真实结构或错误
3. 把结果回流给会话决策层

这里拆成三层表，避免结果只堆在一份 JSON 里：
- `DataMakepoolProbeRun`：一次 probe 请求的主记录
- `DataMakepoolProbeAttempt`：一次具体试跑尝试，记录归一化输入和失败类型
- `DataMakepoolProbeFinding`：结构化发现，用于驱动 draft patch 和后续澄清
"""

from sqlalchemy import Boolean, JSON, Column, DateTime, ForeignKey, Integer, String, Text
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


class DataMakepoolProbeAttempt(Base):  # type: ignore
    """Probe 具体尝试记录。

    设计意图：
    - 一个 `ProbeRun` 在当前版本通常只有一次 attempt
    - 后续如果接入自动重试、换参重试，attempt_no 可以自然扩展
    - `normalized_input_payload` 保存 probe 前真正采用的结构化输入
    """

    __tablename__ = "datamakepool_probe_attempts"

    id = Column(Integer, primary_key=True, index=True)
    probe_run_id = Column(
        Integer,
        ForeignKey("datamakepool_probe_runs.id"),
        nullable=False,
        index=True,
    )
    attempt_no = Column(Integer, nullable=False, default=1)
    normalized_input_payload = Column(JSON, nullable=True)
    raw_result = Column(JSON, nullable=True)
    success = Column(String(16), nullable=False, default="unknown", index=True)
    failure_type = Column(String(64), nullable=True, index=True)
    result_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DataMakepoolProbeFinding(Base):  # type: ignore
    """Probe 结构化发现。

    这层是 probe -> draft patch 闭环的桥：
    - `finding_type / severity / resolved` 便于稳定分类与后续修复
    - `payload` 保留原始上下文，避免后续分析只能回看整份 raw_result
    """

    __tablename__ = "datamakepool_probe_findings"

    id = Column(Integer, primary_key=True, index=True)
    probe_run_id = Column(
        Integer,
        ForeignKey("datamakepool_probe_runs.id"),
        nullable=False,
        index=True,
    )
    probe_attempt_id = Column(
        Integer,
        ForeignKey("datamakepool_probe_attempts.id"),
        nullable=True,
        index=True,
    )
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    step_key = Column(String(128), nullable=True, index=True)
    probe_type = Column(String(32), nullable=False, index=True)
    target_ref = Column(String(255), nullable=True, index=True)
    verdict = Column(String(16), nullable=False, default="unknown", index=True)
    finding_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="info", index=True)
    resolved = Column(Boolean, nullable=False, default=False, index=True)
    detail = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
