"""数据库连接配置与 URL 归一化工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import URL

from .types import normalize_database_type


@dataclass(frozen=True)
class DatabaseConnectionConfig:
    """统一数据库连接配置。

    这层配置会把外部输入的 URL、表单字段、环境变量统一折叠为
    一套内部稳定结构，供 adapter / sql runner / Text2SQL 共用。
    """

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
    """把 SQLAlchemy URL 归一化成统一连接配置。"""

    raw_type = url.drivername.split("+", 1)[0]
    db_type = normalize_database_type(raw_type)
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
