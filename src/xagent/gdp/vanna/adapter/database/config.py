"""数据库连接配置与 URL 归一化工具。

这个模块位于“用户输入的连接信息”和“实际 adapter 运行配置”之间，
负责把不同来源的 URL / driver 方言收敛成平台内部可比较、可复用的统一结构。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import URL, make_url

from .types import try_normalize_database_type


@dataclass(frozen=True)
class DatabaseConnectionConfig:
    """统一数据库连接配置。

    关键字段说明：
    - `db_type`: 平台内部使用的 canonical 数据库类型
    - `database` / `file_path`: 网络型数据库与 SQLite 文件型数据库的两种目标表达
    - `read_only`: 运行层是否必须按只读策略建连
    - `extra`: URL query 中的附加参数，供具体 adapter 再解释
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
    """把 SQLAlchemy URL 归一化成统一连接配置。

    这里故意不再对未知方言直接抛错。
    原因是当前仓库在引入多数据库 adapter 之前，已经允许一些历史
    SQLAlchemy 方言通过 `XAGENT_EXTERNAL_DB_*` 直接工作，例如 `duckdb:///...`。

    因此本函数现在分两类输出：
    - 平台已正式接入的数据库类型：返回 canonical `db_type`
    - 平台未接入但 SQLAlchemy 可能仍可工作的方言：保留原始 driver 基名

    上层可据此决定走 adapter 还是走历史 SQLAlchemy 兼容路径。
    """

    # 这里只解析“连接配置”，不做网络探测；调用方后续可以选择先测连再持久化。
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


def clean_database_name(value: str | None) -> str | None:
    """清洗数据库名，保留展示值但移除空白。"""

    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_database_name(value: str | None) -> str | None:
    """把数据库名归一化成可比较值。

    当前策略只做大小写归一，不主动改写路径、schema 等更强语义，
    避免不同数据库产品的命名规则被错误折叠。
    """

    cleaned = clean_database_name(value)
    if cleaned is None:
        return None
    return cleaned.lower()


def resolve_database_name_from_url(url_str: str) -> str | None:
    """从连接 URL 中推导逻辑数据库名。

    它主要用于旧数据或历史分支里 `database_name` 尚未显式落库时的兜底推导。
    """

    parsed = make_url(url_str)
    config = database_connection_config_from_url(parsed, read_only=True)
    return clean_database_name(config.database or config.file_path)
