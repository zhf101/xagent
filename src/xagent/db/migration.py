import logging
from typing import Any, cast

from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from sqlalchemy import Engine, MetaData, inspect

from .config import create_alembic_config

logger = logging.getLogger(__name__)


def is_database_empty(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    return len(tables) == 0


def get_alembic_revision(engine: Engine) -> str | None:
    """Get the current Alembic revision from the database."""
    with engine.connect() as conn:
        context: Any = MigrationContext.configure(conn)
        return cast(str | None, context.get_current_revision())


def revision_exists(alembic_cfg: Any, revision: str) -> bool:
    """判断某个 revision 是否仍存在于当前代码里的迁移脚本中。"""

    script = ScriptDirectory.from_config(alembic_cfg)
    try:
        return script.get_revision(revision) is not None
    except ResolutionError:
        return False


def reset_database_to_empty(engine: Engine) -> None:
    """破坏性清空当前数据库里的所有表。

    设计目标：
    - 仅用于“历史 revision 已被清理，现存数据库无法继续升级”的收口场景
    - 直接反射并 drop 当前库中的所有表，避免继续依赖旧 revision 链
    """

    metadata = MetaData()
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        metadata.reflect(bind=conn)
        metadata.drop_all(bind=conn)
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def try_upgrade_db(engine: Engine) -> None:
    """按当前单基线迁移链初始化或升级数据库。

    设计原则：
    - 空库：直接执行 `upgrade head`，由 Alembic baseline 负责建整套表
    - 已版本化库：继续 `upgrade head`
    - 非空但无 alembic 版本信息的库：视为脏库，拒绝自动接管
    """
    try:
        logger.info("Starting database upgrade process")
        alembic_cfg = create_alembic_config(engine)
        version = get_alembic_revision(engine)

        if version is None:
            if is_database_empty(engine):
                logger.info(
                    "Creating new database from baseline migration, upgrading to head."
                )
                with engine.connect() as conn:
                    alembic_cfg.attributes["connection"] = conn
                    command.upgrade(alembic_cfg, "head")
            else:
                raise RuntimeError(
                    "Database exists without alembic revision information. "
                    "This project now uses a destructive baseline migration. "
                    "Please reset the database and reinitialize it from head."
                )
        else:
            if not revision_exists(alembic_cfg, version):
                logger.warning(
                    "Current revision %s no longer exists in migration scripts. "
                    "Resetting database destructively and recreating from head.",
                    version,
                )
                reset_database_to_empty(engine)
                with engine.connect() as conn:
                    alembic_cfg.attributes["connection"] = conn
                    command.upgrade(alembic_cfg, "head")
                return

            logger.info(f"Current version: {version}, upgrading to head")
            with engine.connect() as conn:
                alembic_cfg.attributes["connection"] = conn
                command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Automatic database upgrade failed: {e}")
        raise
