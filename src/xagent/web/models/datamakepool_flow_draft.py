"""智能造数平台 FlowDraft 主模型。

FlowDraft 是会话收敛链路中的核心中间工件：
  用户目标 -> 召回 -> 澄清 -> [FlowDraft] -> probe -> readiness gate -> execute

当前版本把粗粒度 JSON 账本升级成：
- 主表：保存版本、状态、摘要、readiness 与 compiled DAG
- 子表：步骤 / 参数 / 映射

这样 decision、probe、execute 都能围绕同一份中间工件工作。
"""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolFlowDraft(Base):  # type: ignore
    """一次会话收敛过程的 flow 草稿工件。

    status 状态机：
        drafting       草稿仍在收敛，结构已建立但尚未达到 probe/execute 就绪
        blocked        已发现明确阻塞项，必须修订参数/映射/候选
        probe_ready    结构完整，允许进入 probe
        compile_ready  probe 关键前提已满足，允许冻结 compiled plan
        execute_ready  readiness gate 判定通过，可正式执行
        archived       被同一会话的新 draft 取代
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
    status = Column(String(32), nullable=False, default="drafting", index=True)

    # 对当前草稿目标的简述，供决策层与执行层直接复用
    goal_summary = Column(Text, nullable=True)

    # 当前草稿锚定的业务系统，便于审批与治理层快速判定
    system_short = Column(String(64), nullable=True, index=True)

    # 当前草稿是否来源于某个候选/资产
    source_candidate_type = Column(String(32), nullable=True, index=True)
    source_candidate_id = Column(String(255), nullable=True, index=True)

    # 步骤合约列表：[{name, type, target_ref, params, dependencies}]
    steps = Column(JSON, nullable=False, default=list)

    # 参数依赖图：{param_name: {source_step, source_field, required}}
    param_graph = Column(JSON, nullable=True)

    # 最新 probe 发现汇总：[{probe_run_id, step_name, verdict, detail}]
    probe_findings = Column(JSON, nullable=True)

    # readiness gate 最新判定：{probe_ready, compile_ready, execute_ready, blockers, score}
    readiness_verdict = Column(JSON, nullable=True)

    # readiness score 拆成单列，方便排序与审计
    readiness_score = Column(Integer, nullable=True)

    # 当前草稿的阻塞原因快照
    blocking_reasons = Column(JSON, nullable=True)

    # 编译后的统一 DAG 载荷，execute 入口应优先消费这个结构
    compiled_dag_payload = Column(JSON, nullable=True)

    # 人工备注，用于审计和调试
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    step_rows = relationship(
        "DataMakepoolFlowDraftStep",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DataMakepoolFlowDraftStep.step_order",
    )
    param_rows = relationship(
        "DataMakepoolFlowDraftParam",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DataMakepoolFlowDraftParam.id",
    )
    mapping_rows = relationship(
        "DataMakepoolFlowDraftMapping",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="DataMakepoolFlowDraftMapping.id",
    )
