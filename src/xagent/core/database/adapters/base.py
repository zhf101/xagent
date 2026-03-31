"""数据库 adapter 协议定义。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..config import DatabaseConnectionConfig


@dataclass(frozen=True)
class QueryExecutionResult:
    """统一查询结果结构。"""

    rows: list[dict[str, Any]]
    affected_rows: int | None = None
    execution_time_ms: int | None = None
    metadata: dict[str, Any] | None = None


class DatabaseAdapter(ABC):
    """所有 SQL 数据库 adapter 共用的最小接口。"""

    family: str
    supported_types: tuple[str, ...]

    def __init__(self, config: DatabaseConnectionConfig):
        self.config = config

    @abstractmethod
    async def connect(self) -> None:
        """建立或预热连接。"""

    @abstractmethod
    async def disconnect(self) -> None:
        """释放连接资源。"""

    @abstractmethod
    async def execute_query(
        self,
        query: str,
        params: list[Any] | dict[str, Any] | None = None,
    ) -> QueryExecutionResult:
        """执行 SQL。"""

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """读取 schema 快照。"""

    @abstractmethod
    def is_write_operation(self, query: str) -> bool:
        """判断 SQL 是否属于写操作。"""
