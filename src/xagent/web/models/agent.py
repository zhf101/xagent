"""Agent Builder models for creating custom AI agents."""

import enum
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class AgentStatus(enum.Enum):
    """Agent status enumeration"""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ExecutionMode(enum.Enum):
    """Agent execution mode enumeration"""

    SIMPLE = "simple"  # Reserved: single LLM call (not implemented yet)
    REACT = "react"  # ReAct pattern for reasoning and acting
    GRAPH = "graph"  # DAG/Graph plan-execute pattern for complex tasks


class Agent(Base):  # type: ignore
    """Custom AI Agent model for agent builder"""

    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True, comment="代理ID")
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        comment="创建用户ID",
    )
    name = Column(
        String(200), nullable=False, comment="代理名称"
    )
    description = Column(Text, nullable=True, comment="代理描述")
    instructions = Column(
        Text, nullable=True, comment="系统提示词/指令"
    )

    # Configuration
    execution_mode = Column(
        String(20),
        nullable=False,
        default="react",
        comment="执行模式（simple/react/graph）",
    )
    models = Column(
        JSON,
        nullable=True,
        comment="模型配置（JSON格式）：{general: id, small_fast: id, visual: id, compact: id}",
    )
    knowledge_bases = Column(
        JSON,
        nullable=True,
        default=list,
        comment="知识库名称列表（JSON格式）",
    )
    skills = Column(
        JSON,
        nullable=True,
        default=list,
        comment="技能名称列表（JSON格式）",
    )
    tool_categories = Column(
        JSON,
        nullable=True,
        default=list,
        comment="工具类别列表（JSON格式）",
    )
    suggested_prompts = Column(
        JSON,
        nullable=True,
        default=list,
        comment="建议提示词示例列表（JSON格式）",
    )

    # Visual
    logo_url = Column(
        String(500), nullable=True, comment="Logo URL"
    )

    # Status
    status: AgentStatus = Column(
        SQLEnum(AgentStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=AgentStatus.DRAFT,
        nullable=False,
        comment="代理状态（draft/published/archived）",
    )  # type: ignore[assignment]
    published_at = Column(
        DateTime(timezone=True), nullable=True, comment="发布时间"
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now,
        nullable=False,
        comment="创建时间",
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
        comment="更新时间",
    )

    # Relationships
    user = relationship("User", back_populates="agents")

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name='{self.name}', status='{self.status}')>"