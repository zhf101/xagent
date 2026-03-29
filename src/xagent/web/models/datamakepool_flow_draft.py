"""智能造数平台 FlowDraft 模型。

FlowDraft 是会话收敛链路中的核心中间工件：
  用户目标 -> 召回 -> 澄清 -> [FlowDraft] -> probe -> readiness gate -> execute

每一轮会话只有一条 active draft（其余状态为 superseded）。
draft 记录步骤合约、参数图、probe 发现与 readiness 判定，
让 decision_engine 能基于这些信号做 ReAct 决策，而不仅仅依赖缺字段规则。
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolFlowDraft(Base):  # type: ignore
    """一次会话收敛过程的 flow 草稿工件。

    status 状态机：
        draft          初始创建，步骤合约已写入，尚未经过 probe
        probe_pending  已触发 probe，等待结果回流
        ready          readiness gate 判定可执行
        superseded     被同一会话的新 draft 取代
    """

    __tablename__ = "datamakepool_flow_drafts"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("datamakepool_conversation_sessions.id"),
        nullable=False,
        index=True,
    )
    # 同一会话内的递增版本号，每次 supersede 后新 draft version+1
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="draft", index=True)

    # 步骤合约列表：[{name, type, target_ref, params, dependencies}]
    steps = Column(JSON, nullable=False, default=list)

    # 参数依赖图：{param_name: {source_step, source_field, required}}
    param_graph = Column(JSON, nullable=True)

    # 最新 probe 发现汇总：[{probe_run_id, step_name, verdict, detail}]
    probe_findings = Column(JSON, nullable=True)

    # readiness gate 最新判定：{ready, blockers, score}
    readiness_verdict = Column(JSON, nullable=True)

    # 人工备注，用于审计和调试
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
