"""记忆系统最核心的数据结构。

`MemoryNote` 是整套记忆能力里最重要的对象，
无论是 in-memory 还是 LanceDB，最终都是围绕它读写。

这次迁移的关键点之一，是在原本只有 `category` 的基础上，
补了 `memory_type` / `memory_subtype` / `scope` 等结构化字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, Field

from .schema import (
    MemoryScope,
    default_category_for_type,
    resolve_memory_subtype,
    resolve_memory_type,
)


class MemoryNote(BaseModel):
    """一条标准化记忆记录。"""
    content: Union[str, bytes]
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    category: str = "general"
    memory_type: Optional[str] = None
    memory_subtype: Optional[str] = None
    scope: str = MemoryScope.USER.value
    timestamp: datetime = Field(default_factory=datetime.now)
    mime_type: str = "text/plain"
    source_session_id: Optional[str] = None
    source_agent_id: Optional[str] = None
    project_id: Optional[str] = None
    workspace_id: Optional[str] = None
    importance: int = 3
    confidence: float = 0.5
    freshness_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    dedupe_key: Optional[str] = None
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        # 这里是迁移兼容的关键逻辑：
        # 即使旧数据只有 category，新版实例化后也会自动补出 memory_type/subtype。
        self.memory_type = resolve_memory_type(self.memory_type, self.category)
        self.memory_subtype = resolve_memory_subtype(
            self.memory_subtype,
            category=self.category,
            metadata=self.metadata,
        )
        if (
            self.category == "general"
            and self.memory_type
            and self.memory_type != "durable"
        ):
            self.category = default_category_for_type(self.memory_type)
        if self.freshness_at is None:
            self.freshness_at = self.timestamp


class MemoryResponse(BaseModel):
    """MemoryStore 统一返回结构，方便不同实现共用同一套接口。"""
    success: bool
    memory_id: Optional[str] = None
    content: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = Field(default_factory=lambda: {})
    search_results: Optional[list[Any]] = None
