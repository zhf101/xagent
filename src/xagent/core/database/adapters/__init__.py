"""SQL 数据库 adapter 导出。"""

from .base import DatabaseAdapter, QueryExecutionResult
from .clickhouse import ClickHouseAdapter
from .dm import DMAdapter
from .factory import create_adapter_for_type
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

__all__ = [
    "DatabaseAdapter",
    "QueryExecutionResult",
    "ClickHouseAdapter",
    "DMAdapter",
    "GaussDBAdapter",
    "GoldenDBAdapter",
    "HighGoAdapter",
    "KingbaseAdapter",
    "MySqlAdapter",
    "OceanBaseAdapter",
    "OracleAdapter",
    "PolarDBAdapter",
    "PostgreSQLAdapter",
    "create_adapter_for_type",
    "SqliteAdapter",
    "SqlServerAdapter",
    "TiDBAdapter",
    "VastbaseAdapter",
]
