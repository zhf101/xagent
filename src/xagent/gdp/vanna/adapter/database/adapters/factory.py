"""数据库 adapter 工厂。"""

from __future__ import annotations

from ..config import DatabaseConnectionConfig
from ..types import normalize_database_type
from .base import DatabaseAdapter
from .clickhouse import ClickHouseAdapter
from .dm import DMAdapter
from .gaussdb import GaussDBAdapter
from .goldendb import GoldenDBAdapter
from .highgo import HighGoAdapter
from .kingbase import KingbaseAdapter
from .mysql import MySqlAdapter
from .oceanbase import OceanBaseAdapter
from .oracle import OracleAdapter
from .polardb import PolarDBAdapter
from .postgresql import PostgreSQLAdapter
from .sqlite import SqliteAdapter
from .sqlserver import SqlServerAdapter
from .tidb import TiDBAdapter
from .vastbase import VastbaseAdapter


ADAPTER_CLASSES: dict[str, type[DatabaseAdapter]] = {
    "mysql": MySqlAdapter,
    "postgresql": PostgreSQLAdapter,
    "oracle": OracleAdapter,
    "sqlserver": SqlServerAdapter,
    "sqlite": SqliteAdapter,
    "dm": DMAdapter,
    "kingbase": KingbaseAdapter,
    "gaussdb": GaussDBAdapter,
    "oceanbase": OceanBaseAdapter,
    "tidb": TiDBAdapter,
    "clickhouse": ClickHouseAdapter,
    "polardb": PolarDBAdapter,
    "vastbase": VastbaseAdapter,
    "highgo": HighGoAdapter,
    "goldendb": GoldenDBAdapter,
}


def create_adapter_for_type(
    db_type: str,
    config: DatabaseConnectionConfig,
) -> DatabaseAdapter:
    """按 canonical 数据库类型返回真实 adapter。"""

    normalized = normalize_database_type(db_type)
    adapter_cls = ADAPTER_CLASSES.get(normalized)
    if adapter_cls is not None:
        return adapter_cls(config)

    raise ValueError(
        f"Database type '{normalized}' is recognized but no adapter is implemented yet"
    )
