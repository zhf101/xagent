"""平台内部统一使用的 SQL 数据库类型定义。"""

from __future__ import annotations

from enum import Enum


class DatabaseType(str, Enum):
    """SQL 数据库 canonical 类型。"""

    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    ORACLE = "oracle"
    SQLSERVER = "sqlserver"
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
    "dameng": DatabaseType.DM.value,
    "dm": DatabaseType.DM.value,
    "opengauss": DatabaseType.GAUSSDB.value,
    "gaussdb": DatabaseType.GAUSSDB.value,
}

DATABASE_TYPE_CANONICAL_VALUES = tuple(item.value for item in DatabaseType)


def normalize_database_type(raw_type: str) -> str:
    """把别名收敛成平台内部稳定的 canonical 数据库类型。"""

    normalized = raw_type.strip().lower()
    normalized = DATABASE_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in DATABASE_TYPE_CANONICAL_VALUES:
        supported = ", ".join(DATABASE_TYPE_CANONICAL_VALUES)
        raise ValueError(
            f"Invalid database type: {raw_type}. Supported types: {supported}"
        )
    return normalized


def try_normalize_database_type(raw_type: str) -> str | None:
    """尽力把数据库类型收敛到 canonical 值。

    这里与 `normalize_database_type()` 的差异是：
    - 已纳入平台治理的数据库类型：返回 canonical 值
    - 平台还没接入但 SQLAlchemy 可能仍能工作的历史方言：返回 `None`

    这样调用方就可以在“不支持新 adapter 能力”和“历史 SQLAlchemy 兼容路径”
    之间做兼容分流，而不是被统一硬拒绝。
    """

    try:
        return normalize_database_type(raw_type)
    except ValueError:
        return None
