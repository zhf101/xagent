"""Web 场景的用户隔离 memory store。

这个模块不实现真正的存储，而是在现有 `MemoryStore` 外面再包一层“按用户隔离”的约束：
- 写入时自动打上 user_id
- 读取、搜索、删除时自动收缩到当前用户
- 这样底层 store 仍可保持通用实现，不必感知 Web 用户体系
"""

import contextvars
from typing import Any, List, Optional

from xagent.core.memory.base import MemoryStore
from xagent.core.memory.core import MemoryNote, MemoryResponse

# Context variable for current user ID
current_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "current_user_id", default=None
)


class UserIsolatedMemoryStore(MemoryStore):
    """基于上下文变量做用户隔离的 memory store 包装器。"""

    def __init__(self, base_store: MemoryStore) -> None:
        """初始化用户隔离包装器。

        `base_store` 才是真正持久化数据的实现；
        当前类只负责把 Web 用户上下文转换成统一过滤条件和写入约束。
        """
        self._base_store = base_store

    def _get_current_user_id(self) -> Optional[int]:
        """从上下文变量读取当前用户 id。"""
        return current_user_id.get()

    def _add_user_filter(
        self, filters: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """给现有 filters 追加用户隔离条件。

        这里统一把 user_id 放进 `metadata.user_id`，
        这样底层 store 不需要认识“用户”这个 Web 概念，也能完成隔离。
        """
        if filters is None:
            filters = {}

        # Add user ID to metadata filters
        metadata_filters = filters.get("metadata", {})
        user_id = self._get_current_user_id()
        if user_id is not None:
            metadata_filters["user_id"] = user_id

        filters["metadata"] = metadata_filters
        return filters

    def add(self, note: MemoryNote) -> MemoryResponse:
        """写入一条带用户隔离的记忆。

        状态影响：
        - 会在 note.metadata 上补入当前 user_id
        - 然后把真正写入动作委托给底层 store
        """
        # Add user ID to metadata for isolation
        user_id = self._get_current_user_id()
        if user_id is not None:
            note.metadata["user_id"] = user_id

        return self._base_store.add(note)

    def get(self, note_id: str) -> MemoryResponse:
        """读取一条记忆，并校验其归属当前用户。"""
        response = self._base_store.get(note_id)
        if response.success and response.content:
            note = response.content
            # Check if the note belongs to the user
            user_id = self._get_current_user_id()
            if user_id is not None and note.metadata.get("user_id") != user_id:
                return MemoryResponse(
                    success=False,
                    error="Memory note not found or access denied",
                    memory_id=note_id,
                )

        return response

    def update(self, note: MemoryNote) -> MemoryResponse:
        """更新一条记忆，并先校验所有权。"""
        # First verify ownership
        user_id = self._get_current_user_id()
        if user_id is not None and note.id:
            existing_response = self.get(note.id)
            if not existing_response.success:
                return existing_response

        # Add user ID to metadata if not present
        if user_id is not None and "user_id" not in note.metadata:
            note.metadata["user_id"] = user_id

        return self._base_store.update(note)

    def delete(self, note_id: str) -> MemoryResponse:
        """删除一条记忆，并先校验所有权。"""
        # First verify ownership
        user_id = self._get_current_user_id()
        if user_id is not None:
            existing_response = self.get(note_id)
            if not existing_response.success:
                return existing_response

        return self._base_store.delete(note_id)

    def search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[dict[str, Any]] = None,
        similarity_threshold: Optional[float] = None,
    ) -> List[MemoryNote]:
        """按用户隔离条件搜索记忆。"""
        # Add user filter to existing filters
        filtered_filters = self._add_user_filter(filters)

        return self._base_store.search(
            query=query,
            k=k,
            filters=filtered_filters,
            similarity_threshold=similarity_threshold,
        )

    def clear(self) -> None:
        """清空当前用户可见记忆。

        若当前没有用户上下文，则退化为清空整个底层 store；
        这是给系统级管理或测试场景保留的能力。
        """
        user_id = self._get_current_user_id()
        if user_id is not None:
            # Only clear notes for this user
            user_notes = self.list_all(filters={"metadata": {"user_id": user_id}})
            for note in user_notes:
                self._base_store.delete(note.id)
        else:
            # Clear all notes
            self._base_store.clear()

    def list_all(
        self,
        filters: Optional[dict[str, Any]] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[MemoryNote]:
        """列出当前用户可见的全部记忆。

        这里的分页必须发生在“先补齐 user_id 过滤条件之后”，
        否则 offset/limit 会先作用到全局集合，导致不同用户之间出现可见性串页。
        """
        # Add user filter to existing filters
        filtered_filters = self._add_user_filter(filters)

        return self._base_store.list_all(
            filtered_filters,
            limit=limit,
            offset=offset,
        )

    def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """返回当前用户视角下的记忆数量。"""
        filtered_filters = self._add_user_filter(filters)
        return self._base_store.count(filtered_filters)

    def get_stats(self) -> dict[str, Any]:
        """返回当前用户视角下的记忆统计信息。"""
        user_id = self._get_current_user_id()
        if user_id is not None:
            # Get stats for specific user
            user_notes = self.list_all()
            base_stats = self._base_store.get_stats()
            stats = self._calculate_stats(user_notes)
            # Preserve the original memory store type from base store
            stats["memory_store_type"] = base_stats.get("memory_store_type", "unknown")
            return stats
        else:
            # Get global stats
            return self._base_store.get_stats()

    def _calculate_stats(self, notes: List[MemoryNote]) -> dict[str, Any]:
        """基于指定记忆集合计算轻量统计。"""
        total_count = len(notes)
        category_counts: dict[str, int] = {}
        tag_counts: dict[str, int] = {}

        for note in notes:
            # Count by category
            category_counts[note.category] = category_counts.get(note.category, 0) + 1

            # Count tags
            for tag in note.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        return {
            "total_count": total_count,
            "category_counts": category_counts,
            "tag_counts": tag_counts,
        }


def set_user_context(user_id: Optional[int]) -> contextvars.Token:
    """设置当前线程/协程上下文中的用户 id。"""
    return current_user_id.set(user_id)


def reset_user_context(token: contextvars.Token) -> None:
    """把用户上下文恢复到之前状态。"""
    current_user_id.reset(token)


class UserContext:
    """设置用户上下文的上下文管理器。

    这个类的价值是避免业务代码手动 set/reset 时遗漏恢复，导致后续请求串用户。
    """

    def __init__(self, user_id: Optional[int]) -> None:
        self.user_id = user_id
        self.token: Optional[contextvars.Token] = None

    def __enter__(self) -> "UserContext":
        self.token = set_user_context(self.user_id)
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Optional[object],
    ) -> None:
        if self.token is not None:
            reset_user_context(self.token)
