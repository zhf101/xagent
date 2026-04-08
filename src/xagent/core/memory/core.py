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
    """一条标准化记忆记录。

    这是 memory 领域最核心的领域模型，所有 store、任务、检索结果最终都会围绕它流转。
    关键字段说明：

    - `content`: 记忆正文，允许文本或二进制内容
    - `category`: 旧版分类字段，当前仍保留给兼容层和旧调用方使用
    - `memory_type / memory_subtype`: 新版结构化分类，用于更稳定的过滤和治理
    - `scope`: 记忆作用域，决定它更偏用户态、会话态还是更广域上下文
    - `metadata`: 预留给业务层扩展的附加信息，不应替代上面的核心字段
    """
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
        """在实例化后补齐迁移兼容字段。

        这里做的不是普通默认值填充，而是“旧数据向新结构迁移”的关键收口点：
        - 旧数据只有 `category` 时，自动推导 `memory_type / memory_subtype`
        - 对 general + 明确 memory_type 的场景，回写更合理的 category
        - 若没有 freshness_at，就默认以 timestamp 作为新鲜度起点
        """
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
    """MemoryStore 统一返回结构，方便不同实现共用同一套接口。

    这个响应模型的目的，是让 in-memory、LanceDB、pgvector 甚至未来其他 store
    都能对上层暴露同一种交互契约，而不是把底层异常与返回值格式泄漏出去。
    """
    success: bool
    memory_id: Optional[str] = None
    content: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[dict[str, Any]] = Field(default_factory=lambda: {})
    search_results: Optional[list[Any]] = None
