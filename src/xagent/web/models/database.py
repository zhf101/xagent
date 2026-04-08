"""Web 层数据库初始化与会话管理。

这个文件仍然是 ORM 模型注册入口，但职责已经和过去明显不同：
- 负责创建 Engine / Session
- 负责导入模型，让 ORM 关系和 metadata 完整可用
- 负责校验“数据库是否已经由 SQL 脚本初始化好”

明确不再做的事情：
- 不再自动跑 Alembic
- 不再自动 `create_all()`
- 不再把运行时启动当成数据库建模入口

这样做的目标很直接：
- 数据库结构的来源只能是 `db/postgresql/init.sql + patches/*.sql`
- Web 进程只消费既有 schema，不再偷偷改库
"""

import logging
from typing import Any, Generator

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from ...config import get_database_url

_SessionLocal: sessionmaker[Session] | None = None

_engine: Engine | None = None

# Create base model class
# Mypy workaround: explicitly type Base as Any to avoid "variable not valid as type" error
Base: Any = declarative_base()


def _verify_required_tables_exist(engine: Engine) -> None:
    """校验主库必需表是否已经存在。

    现在数据库结构由 SQL 脚本统一维护，所以启动阶段只允许“验库”，不允许“补库”。
    这里直接以 `Base.metadata` 已注册的表为准做一次全量校验，优点是：
    - 新增 ORM 表后，这里的检查会自动跟上
    - 不需要手写另一份“必需表名单”再维护两套真相

    失败时返回尽量明确的指引，避免开发同学只看到一串底层 SQLAlchemy 异常，
    却不知道应该去执行哪份 SQL。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names(schema="public"))
    required_tables = {
        table.name
        for table in Base.metadata.sorted_tables
        if (table.schema or "public") == "public"
    }
    missing_tables = sorted(required_tables - existing_tables)
    if not missing_tables:
        return

    raise RuntimeError(
        "PostgreSQL schema is not initialized. Missing tables: "
        f"{', '.join(missing_tables)}. "
        "Please initialize the database with db/postgresql/init.sql "
        "and then apply any required db/postgresql/patches/*.sql manually."
    )


def _verify_database_connectivity(engine: Engine) -> None:
    """做一次最小连通性校验。

    这里保留 `SELECT 1` 的原因不是为了“证明数据库没问题”，
    而是尽早把连接串、认证失败、网络不可达这类基础问题在启动阶段暴露出来。
    """
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db() -> Generator[Session, None, None]:
    """返回一次请求级数据库会话。

    这个生成器是 FastAPI 依赖注入最常用的数据库入口。
    约束很明确：
    - 调用前必须先执行 `init_db()`
    - 调用方不负责 close，生成器 finally 会统一释放
    """
    if _SessionLocal is None:
        raise RuntimeError("Session Local is not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_local() -> sessionmaker[Session]:
    """返回底层 sessionmaker。

    只有在需要手动管理多次短会话、或非 FastAPI 场景下才应该直接拿这个工厂。
    普通 API/service 优先通过 `get_db()` 获取 request scoped session。
    """
    if _SessionLocal is None:
        raise RuntimeError("Session Local is not initialized. Call init_db() first.")
    return _SessionLocal


def get_engine() -> Engine:
    """返回当前全局 Engine。"""
    if _engine is None:
        raise RuntimeError("Engine is not initialized. Call init_db() first.")
    return _engine


def init_db(db_url: str | None = None) -> None:
    """初始化数据库引擎、会话工厂，并校验 schema 已存在。

    这里是 Web 进程里数据库侧最核心的入口，职责包含：
    1. 解析数据库 URL
    2. 创建 Engine 和 sessionmaker
    3. 显式导入模型，确保 ORM metadata 完整
    4. 校验数据库连通性与主表完整性

    这里刻意不再承担任何 DDL 职责。
    如果库没建好，应该直接失败并提示去执行 SQL 脚本，
    而不是在服务启动时偷偷补表、改列或推进迁移版本。
    """
    # 这里的导入虽然看起来“没被直接使用”，但实际上非常关键：
    # SQLAlchemy 只有在模型类被 import 后，才会把表注册到 Base.metadata。
    # 所以本次新增的 MemoryJob 也必须在这里显式导入。
    from . import (  # noqa: F401
        MCPServer,
        MemoryJob,
        Model,
        SystemSetting,
        Task,
        TaskChatMessage,
        TemplateStats,
        ToolConfig,
        ToolUsage,
        UploadedFile,
        User,
        UserDefaultModel,
        UserModel,
    )
    from .agent import Agent  # noqa: F401
    from ...gdp.hrun.model.http_resource import GdpHttpResource  # noqa: F401
    from .sandbox import SandboxInfo  # noqa: F401
    from .system_registry import SystemRegistry, UserSystemRole  # noqa: F401
    from ...gdp.vanna.model.text2sql import Text2SQLDatabase  # noqa: F401
    from ...gdp.vanna.model.vanna import (  # noqa: F401
        VannaAskRun,
        VannaEmbeddingChunk,
        VannaKnowledgeBase,
        VannaSchemaColumn,
        VannaSchemaColumnAnnotation,
        VannaSchemaHarvestJob,
        VannaSchemaTable,
        VannaSqlAsset,
        VannaSqlAssetRun,
        VannaSqlAssetVersion,
        VannaTrainingEntry,
    )

    global _SessionLocal
    global _engine

    # Database configuration
    if db_url is not None:
        database_url = db_url
    else:
        database_url = get_database_url()

    # 虽然项目主线已转为 PostgreSQL-first，这里仍保留 SQLite 显式分支，
    # 主要是为了不把现有测试夹具一次性全部打断。
    # 但业务运行时默认不会再落到 SQLite；只有调用方明确传 sqlite URL 时才会走这里。
    if "sqlite" in database_url:
        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,  # SQLite doesn't need connection pooling
        )
    else:
        _engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,  # 30 seconds timeout for getting connection from pool
            pool_recycle=3600,  # Recycle connections after 1 hour
            pool_pre_ping=True,  # Verify connections before using
        )

    # Create session factory
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    _verify_database_connectivity(_engine)
    _verify_required_tables_exist(_engine)

    logger = logging.getLogger(__name__)
    logger.info("Database engine initialized and schema presence verified.")
