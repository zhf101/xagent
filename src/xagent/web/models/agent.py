"""Agent Builder 宿主模型。

这里保存的是用户在平台里配置出来的自定义 Agent 元信息，
重点是描述 agent 的能力组合，不直接承载一次任务运行态。
"""

import enum
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class AgentStatus(enum.Enum):
    """Agent 生命周期状态。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ExecutionMode(enum.Enum):
    """Agent 执行模式枚举。"""

    SIMPLE = "simple"  # Reserved: single LLM call (not implemented yet)
    REACT = "react"  # ReAct pattern for reasoning and acting
    GRAPH = "graph"  # DAG/Graph plan-execute pattern for complex tasks


class Agent(Base):  # type: ignore
    """自定义 Agent 宿主模型。

    关键字段说明：
    - `instructions`: agent 级系统指令
    - `execution_mode`: 该 agent 采用哪种执行模式
    - `models`: 该 agent 显式绑定的模型集合
    - `knowledge_bases / skills / tool_categories`: agent 可用知识、技能和工具范围
    - `status / published_at`: 当前是否对外可用
    """

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    instructions = Column(Text, nullable=True)  # System prompt/instructions

    # Configuration
    execution_mode = Column(
        String(20), nullable=False, default="react"
    )  # Execution mode: simple, react, graph
    models = Column(
        JSON, nullable=True
    )  # Model config: {general: id, small_fast: id, visual: id, compact: id}
    knowledge_bases = Column(JSON, nullable=True, default=list)  # List of KB names
    skills = Column(JSON, nullable=True, default=list)  # List of skill names
    tool_categories = Column(
        JSON, nullable=True, default=list
    )  # List of tool categories
    suggested_prompts = Column(
        JSON, nullable=True, default=list
    )  # List of suggested prompt examples for users

    # Visual
    logo_url = Column(String(500), nullable=True)

    # Status
    status: AgentStatus = Column(
        SQLEnum(AgentStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=AgentStatus.DRAFT,
        nullable=False,
    )  # type: ignore[assignment]
    published_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="agents")

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name='{self.name}', status='{self.status}')>"
