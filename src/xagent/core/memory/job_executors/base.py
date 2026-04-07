"""后台记忆任务执行器的抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import nullcontext
from typing import Any, Optional


class MemoryJobExecutor(ABC):
    def __init__(self, memory_store_manager: Optional[Any] = None) -> None:
        # 允许外部显式传入 manager，方便测试；
        # 正常运行时则从 web.dynamic_memory_store 动态获取。
        self._memory_store_manager = memory_store_manager

    @property
    @abstractmethod
    def job_type(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        *,
        job_payload: dict[str, Any],
        job_id: Optional[int] = None,
        source_user_id: Optional[int] = None,
        source_session_id: Optional[str] = None,
        source_project_id: Optional[str] = None,
        source_task_id: Optional[str] = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _get_memory_store(self):
        """拿到底层 memory store，供具体 executor 读写记忆。"""
        if self._memory_store_manager is not None:
            return self._memory_store_manager.get_memory_store()

        from ....web.dynamic_memory_store import get_memory_store_manager

        return get_memory_store_manager().get_memory_store()

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_user_context(user_id: Optional[int]):
        """为后台线程补上用户隔离上下文，避免跨用户访问记忆。"""
        if user_id is None:
            return nullcontext()

        try:
            from ....web.user_isolated_memory import UserContext

            return UserContext(user_id)
        except ImportError:
            return nullcontext()
