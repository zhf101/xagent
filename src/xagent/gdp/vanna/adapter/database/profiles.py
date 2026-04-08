"""SQL 数据库接入模板与支持深度注册表。

它定义的是“平台目前如何看待每一种数据库产品”，包括展示名、默认端口、
接入级别、依赖驱动和备注。前台表单、帮助信息、后端兼容逻辑都会复用这里。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .types import normalize_database_type


@dataclass(frozen=True)
class DatabaseProfile:
    """描述单种 SQL 数据库在平台里的接入方式。

    关键字段说明：
    - `db_type`: 平台内部 canonical 类型
    - `support_level`: 当前代码分支对它支持到什么深度
    - `driver_packages`: 宿主机需要具备的驱动依赖
    - `connection_example`: 给用户或前端展示的标准连接示例
    """

    db_type: str
    display_name: str
    default_port: int | None
    category: str
    protocol: str
    support_level: str
    aliases: tuple[str, ...]
    driver_packages: tuple[str, ...]
    connection_example: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


DATABASE_PROFILES: tuple[DatabaseProfile, ...] = (
    DatabaseProfile(
        db_type="mysql",
        display_name="MySQL",
        default_port=3306,
        category="开源",
        protocol="sql",
        support_level="full",
        aliases=(),
        driver_packages=("pymysql", "mysql-connector-python"),
        connection_example="mysql+pymysql://user:password@host:3306/database",
        notes=("使用独立 MySQL adapter。",),
    ),
    DatabaseProfile(
        db_type="postgresql",
        display_name="PostgreSQL",
        default_port=5432,
        category="开源",
        protocol="sql",
        support_level="full",
        aliases=("postgres",),
        driver_packages=("psycopg2-binary",),
        connection_example="postgresql+psycopg2://user:password@host:5432/database",
        notes=("使用独立 PostgreSQL adapter。",),
    ),
    DatabaseProfile(
        db_type="oracle",
        display_name="Oracle",
        default_port=1521,
        category="商业",
        protocol="sql",
        support_level="full",
        aliases=(),
        driver_packages=("oracledb",),
        connection_example="oracle+oracledb://user:password@host:1521/?service_name=orclpdb1",
        notes=("使用独立 Oracle adapter，通过 service_name 建连。",),
    ),
    DatabaseProfile(
        db_type="sqlserver",
        display_name="SQL Server",
        default_port=1433,
        category="商业",
        protocol="sql",
        support_level="full",
        aliases=("mssql",),
        driver_packages=("pymssql", "pyodbc"),
        connection_example="mssql+pymssql://user:password@host:1433/database",
        notes=("默认走 pymssql；如需 ODBC 可在 query 中附加 driver。",),
    ),
    DatabaseProfile(
        db_type="sqlite",
        display_name="SQLite",
        default_port=None,
        category="嵌入式",
        protocol="sql",
        support_level="full",
        aliases=(),
        driver_packages=(),
        connection_example="sqlite:///C:/data/demo.sqlite",
        notes=("本地文件数据库，无需额外驱动。",),
    ),
    DatabaseProfile(
        db_type="dm",
        display_name="达梦",
        default_port=5236,
        category="国产",
        protocol="sql",
        support_level="full-with-odbc",
        aliases=("dameng",),
        driver_packages=("pyodbc",),
        connection_example="dm://user:password@host:5236/database?odbc_driver=DM8 ODBC DRIVER",
        notes=("使用独立 DM adapter，当前通过 ODBC 执行；需要宿主机安装达梦 ODBC 驱动。",),
    ),
    DatabaseProfile(
        db_type="kingbase",
        display_name="人大金仓",
        default_port=54321,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("psycopg2-binary",),
        connection_example="kingbase://user:password@host:54321/database",
        notes=("使用独立 Kingbase adapter。",),
    ),
    DatabaseProfile(
        db_type="gaussdb",
        display_name="华为 GaussDB",
        default_port=5432,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=("opengauss",),
        driver_packages=("psycopg2-binary",),
        connection_example="gaussdb://user:password@host:5432/database",
        notes=("使用独立 GaussDB adapter。",),
    ),
    DatabaseProfile(
        db_type="oceanbase",
        display_name="蚂蚁 OceanBase",
        default_port=2881,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("pymysql",),
        connection_example="oceanbase://user:password@host:2881/database",
        notes=("使用独立 OceanBase adapter。",),
    ),
    DatabaseProfile(
        db_type="tidb",
        display_name="TiDB",
        default_port=4000,
        category="分布式",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("pymysql",),
        connection_example="tidb://user:password@host:4000/database",
        notes=("使用独立 TiDB adapter。",),
    ),
    DatabaseProfile(
        db_type="clickhouse",
        display_name="ClickHouse",
        default_port=8123,
        category="OLAP",
        protocol="sql",
        support_level="full",
        aliases=(),
        driver_packages=("clickhouse-connect",),
        connection_example="clickhouse://user:password@host:8123/database",
        notes=("当前默认按 HTTP 接口建连。",),
    ),
    DatabaseProfile(
        db_type="polardb",
        display_name="阿里云 PolarDB",
        default_port=3306,
        category="云数据库",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("pymysql",),
        connection_example="polardb://user:password@host:3306/database",
        notes=("使用独立 PolarDB adapter。",),
    ),
    DatabaseProfile(
        db_type="vastbase",
        display_name="海量 Vastbase",
        default_port=5432,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("psycopg2-binary",),
        connection_example="vastbase://user:password@host:5432/database",
        notes=("使用独立 Vastbase adapter。",),
    ),
    DatabaseProfile(
        db_type="highgo",
        display_name="瀚高 HighGo",
        default_port=5866,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("psycopg2-binary",),
        connection_example="highgo://user:password@host:5866/database",
        notes=("使用独立 HighGo adapter。",),
    ),
    DatabaseProfile(
        db_type="goldendb",
        display_name="中兴 GoldenDB",
        default_port=3306,
        category="国产",
        protocol="sql",
        support_level="dedicated-adapter",
        aliases=(),
        driver_packages=("pymysql",),
        connection_example="goldendb://user:password@host:3306/database",
        notes=("使用独立 GoldenDB adapter。",),
    ),
)


def list_database_profiles() -> list[dict]:
    """返回全部 SQL 数据库接入模板。"""

    return [profile.to_dict() for profile in DATABASE_PROFILES]


def get_database_profile(db_type: str) -> dict:
    """按 canonical/alias 查询单个 SQL 数据库模板。

    统一先做类型归一化，避免前台和后端分别维护一套别名规则。
    """

    normalized = normalize_database_type(db_type)
    for profile in DATABASE_PROFILES:
        if profile.db_type == normalized:
            return profile.to_dict()
    raise ValueError(f"Database profile not found: {db_type}")
