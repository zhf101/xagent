import logging
from typing import Any, cast

from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Engine, MetaData, String, Table, inspect, text
from sqlalchemy.engine import Connection

from .config import create_alembic_config

logger = logging.getLogger(__name__)

ALEMBIC_VERSION_COLUMN_LENGTH = 255


def is_database_empty(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    return len(tables) == 0


def get_alembic_revision(engine: Engine) -> str | None:
    """Get the current Alembic revision from the database."""
    with engine.connect() as conn:
        context: Any = MigrationContext.configure(conn)
        return cast(str | None, context.get_current_revision())


def ensure_alembic_version_table_supports_long_revision_ids(conn: Connection) -> None:
    """确保 `alembic_version.version_num` 能容纳当前项目的长 revision。

    这个项目的最新 revision 已经超过 Alembic 默认的 32 字符长度。
    对“全新开发库”来说，我们并不想强行跑完整迁移链，因为很多历史迁移本来就不是
    为“从绝对空库一步步建到今天”设计的；开发环境更合理的路径是：

    1. 先把版本表准备好
    2. 直接 `stamp(head)` 记录当前 schema 目标版本
    3. 数据库结构应已通过 db/postgresql/init.sql 初始化

    因此这里的职责非常聚焦：
    - 如果版本表还不存在，就按更宽的 `varchar(255)` 直接创建
    - 如果版本表已存在且仍是较短长度，则只在 PostgreSQL 上执行扩容
    - SQLite 不强制长度，保留现状即可
    """
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    if "alembic_version" not in existing_tables:
        Table(
            "alembic_version",
            MetaData(),
            Column(
                "version_num",
                String(ALEMBIC_VERSION_COLUMN_LENGTH),
                nullable=False,
                primary_key=True,
            ),
        ).create(bind=conn)
        return

    columns = {column["name"]: column for column in inspector.get_columns("alembic_version")}
    version_num_column = columns.get("version_num")
    current_length = None
    if version_num_column is not None and hasattr(version_num_column.get("type"), "length"):
        current_length = version_num_column["type"].length

    if current_length is not None and current_length >= ALEMBIC_VERSION_COLUMN_LENGTH:
        return

    if conn.dialect.name == "postgresql":
        conn.execute(
            text(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE varchar(255)"
            )
        )


def try_upgrade_db(engine: Engine) -> None:
    """尝试把数据库推进到当前 Alembic head。

    当前项目对“开发环境全新空库”和“已有历史数据的库”采用两条不同策略：
    - 空库：先执行 db/postgresql/init.sql 初始化表结构，再 stamp(head) 标记版本
      这是因为部分老迁移依赖若干基础表先存在，更适合做增量演进，不适合从零建库
    - 非空且已有 revision：继续按正常 Alembic `upgrade(head)` 升级
    - 非空但没有 revision：视为脏状态，要求人工处理，避免误判现有数据结构
    """
    try:
        logger.info("Starting database upgrade process")
        alembic_cfg = create_alembic_config(engine)
        version = get_alembic_revision(engine)

        if version is None:
            if is_database_empty(engine):
                # 开发环境的全新数据库初始化走“直接建最终态”路径：
                # 先把 Alembic 版本表准备成支持长 revision 的结构，再只写入 head 版本号。
                # 建表动作由 db/postgresql/init.sql 完成，此处仅做版本标记。
                logger.info("Creating new database, stamping with latest revision.")
                with engine.begin() as conn:
                    ensure_alembic_version_table_supports_long_revision_ids(conn)
                    alembic_cfg.attributes["connection"] = conn
                    command.stamp(alembic_cfg, "head")
            else:
                raise RuntimeError(
                    "Database exists without alembic revision information. Please initialize the database schema version manually by running: alembic stamp <revision>"
                )
        else:
            logger.info(f"Current version: {version}, upgrading to head")
            with engine.connect() as conn:
                alembic_cfg.attributes["connection"] = conn
                command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Automatic database upgrade failed: {e}")
        raise
