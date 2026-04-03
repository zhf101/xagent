"""数据库连接配置与 URL 归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import URL

from .types import try_normalize_database_type


@dataclass(frozen=True)
class DatabaseConnectionConfig:
    """统一数据库连接配置。"""

    db_type: str
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    database: str | None = None
    file_path: str | None = None
    read_only: bool = True
    extra: dict[str, Any] | None = None


def database_connection_config_from_url(
    url: URL,
    *,
    read_only: bool = True,
) -> DatabaseConnectionConfig:
    """把 SQLAlchemy URL 归一化成统一连接配置。

    这里故意不再对未知方言直接抛错。
    原因是当前仓库在引入多数据库 adapter 之前，已经允许一些历史
    SQLAlchemy 方言通过 `XAGENT_EXTERNAL_DB_*` 直接工作，例如 `duckdb:///...`。

    因此本函数现在分两类输出：
    - 平台已正式接入的数据库类型：返回 canonical `db_type`
    - 平台未接入但 SQLAlchemy 可能仍可工作的方言：保留原始 driver 基名

    上层可据此决定走 adapter 还是走历史 SQLAlchemy 兼容路径。
    """

    raw_type = url.drivername.split("+", 1)[0]
    db_type = try_normalize_database_type(raw_type) or raw_type.strip().lower()
    extra = dict(url.query) if url.query else {}

    return DatabaseConnectionConfig(
        db_type=db_type,
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database=None if db_type == "sqlite" else url.database,
        file_path=url.database if db_type == "sqlite" else None,
        read_only=read_only,
        extra=extra or None,
    )
