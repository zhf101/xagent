"""数据库 adapter 协议定义。

这一层定义的是 Vanna 与具体数据库驱动之间的最小公共契约。
新增数据库方言时，首先要满足这里的抽象接口，其他 service 才能无差别复用。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..config import DatabaseConnectionConfig


@dataclass(frozen=True)
class QueryExecutionResult:
    """统一查询结果结构。

    它的设计目标是屏蔽各家驱动在返回值格式上的差异，统一抽象成：
    - `rows`: 结构化结果集
    - `affected_rows`: 受影响行数
    - `execution_time_ms / metadata`: 便于诊断的附加信息
    """

    rows: list[dict[str, Any]]
    affected_rows: int | None = None
    execution_time_ms: int | None = None
    metadata: dict[str, Any] | None = None


class DatabaseAdapter(ABC):
    """所有 SQL 数据库 adapter 共用的最小接口。

    这里故意不暴露驱动私有能力，只保留问答链路真正需要的四件事：
    建连、断连、执行 SQL、读取 schema。
    """

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
        """执行 SQL。

        调用方默认假设这里已经做好读写限制、自身参数绑定和结果标准化。
        """

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """读取 schema 快照。

        返回值约定为适合 `SchemaHarvestService` / `AskService` 继续消费的统一结构。
        """

    @abstractmethod
    def is_write_operation(self, query: str) -> bool:
        """判断 SQL 是否属于写操作。"""
