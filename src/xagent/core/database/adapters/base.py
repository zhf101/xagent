"""Base adapter protocol for xagent database integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..config import DatabaseConnectionConfig


@dataclass(frozen=True)
class QueryExecutionResult:
    rows: list[dict[str, Any]]
    affected_rows: int | None = None
    execution_time_ms: int | None = None
    metadata: dict[str, Any] | None = None


class DatabaseAdapter(ABC):
    """Common adapter interface shared by Text2SQL and datamakepool."""

    family: str
    supported_types: tuple[str, ...]

    def __init__(self, config: DatabaseConnectionConfig):
        self.config = config

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def execute_query(
        self, query: str, params: list[Any] | None = None
    ) -> QueryExecutionResult: ...

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    def is_write_operation(self, query: str) -> bool: ...
