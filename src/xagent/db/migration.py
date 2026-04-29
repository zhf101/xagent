import logging
from typing import Any, cast

from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect

from .config import create_alembic_config

logger = logging.getLogger(__name__)


def is_database_empty(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    return len(tables) == 0


def get_alembic_revision(engine: Engine) -> str | None:
    """获取数据库对应的当前 Alembic 版本号。"""
    with engine.connect() as conn:
        context: Any = MigrationContext.configure(conn)
        return cast(str | None, context.get_current_revision())


def try_upgrade_db(engine: Engine) -> None:
    """将数据库升级到最新版本（全新数据库则标记为最新版本）。"""
    try:
        logger.info("Starting database upgrade process")
        alembic_cfg = create_alembic_config(engine)
        version = get_alembic_revision(engine)

        if version is None:
            if is_database_empty(engine):
                logger.info("Creating new database, stamping to latest revision.")
                with engine.connect() as conn:
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
