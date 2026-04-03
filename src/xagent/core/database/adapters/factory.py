"""数据库 adapter 工厂。"""

from __future__ import annotations

from ..config import DatabaseConnectionConfig
from ..types import normalize_database_type
from .base import DatabaseAdapter
from .clickhouse import ClickHouseAdapter
from .mysql_family import MySqlFamilyAdapter
from .oracle_family import OracleFamilyAdapter
from .postgres_family import PostgresFamilyAdapter
from .sqlite import SqliteAdapter
from .sqlserver import SqlServerAdapter


def create_adapter_for_type(
    db_type: str,
    config: DatabaseConnectionConfig,
) -> DatabaseAdapter:
    """按 canonical 数据库类型返回真实 adapter。"""

    normalized = normalize_database_type(db_type)

    if normalized in PostgresFamilyAdapter.supported_types:
        return PostgresFamilyAdapter(config)
    if normalized in MySqlFamilyAdapter.supported_types:
        return MySqlFamilyAdapter(config)
    if normalized in OracleFamilyAdapter.supported_types:
        return OracleFamilyAdapter(config)
    if normalized in SqlServerAdapter.supported_types:
        return SqlServerAdapter(config)
    if normalized in SqliteAdapter.supported_types:
        return SqliteAdapter(config)
    if normalized in ClickHouseAdapter.supported_types:
        return ClickHouseAdapter(config)

    raise ValueError(
        f"Database type '{normalized}' is recognized but no adapter is implemented yet"
    )
