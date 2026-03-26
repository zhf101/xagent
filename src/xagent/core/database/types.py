"""Canonical database type definitions for xagent."""

from __future__ import annotations

from enum import Enum


class DatabaseType(str, Enum):
    """Canonical database types shared by Text2SQL and datamakepool."""

    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    REDIS = "redis"
    ORACLE = "oracle"
    SQLSERVER = "sqlserver"
    MONGODB = "mongodb"
    SQLITE = "sqlite"
    DM = "dm"
    KINGBASE = "kingbase"
    GAUSSDB = "gaussdb"
    OCEANBASE = "oceanbase"
    TIDB = "tidb"
    CLICKHOUSE = "clickhouse"
    POLARDB = "polardb"
    VASTBASE = "vastbase"
    HIGHGO = "highgo"
    GOLDENDB = "goldendb"


DATABASE_TYPE_ALIASES: dict[str, str] = {
    "postgres": DatabaseType.POSTGRESQL.value,
    "postgresql": DatabaseType.POSTGRESQL.value,
    "mssql": DatabaseType.SQLSERVER.value,
    "sqlserver": DatabaseType.SQLSERVER.value,
    "mongo": DatabaseType.MONGODB.value,
    "mongodb": DatabaseType.MONGODB.value,
    "dameng": DatabaseType.DM.value,
    "dm": DatabaseType.DM.value,
    "opengauss": DatabaseType.GAUSSDB.value,
    "gaussdb": DatabaseType.GAUSSDB.value,
}

DATABASE_TYPE_CANONICAL_VALUES = tuple(item.value for item in DatabaseType)


def normalize_database_type(raw_type: str) -> str:
    """Normalize aliases to canonical database type values."""
    normalized = raw_type.strip().lower()
    normalized = DATABASE_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in DATABASE_TYPE_CANONICAL_VALUES:
        supported = ", ".join(DATABASE_TYPE_CANONICAL_VALUES)
        raise ValueError(
            f"Invalid database type: {raw_type}. Supported types: {supported}"
        )
    return normalized
