import logging
from typing import Any, cast

from alembic import command
from alembic.util.exc import CommandError
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
    except (ResolutionError, CommandError):
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


def get_missing_declared_tables(engine: Engine) -> list[str]:
    """检查当前数据库是否缺少 ORM 已声明的表。

    当前仓库采用“单基线 + ORM 真相源”策略：
    - 新空库通过 baseline migration 一次性创建整套表
    - 若代码里的 ORM 已声明新表，但当前数据库仍停在旧结构，
      仅执行 `upgrade head` 不会补这些表，因此需要显式探测 schema drift
    """

    try:
        from xagent.web import models as web_models  # noqa: F401
        from xagent.web.models.database import Base

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        declared_tables = set(Base.metadata.tables.keys())
        return sorted(declared_tables - existing_tables)
    except Exception as exc:
        logger.warning("Failed to inspect schema drift, skipping check: %s", exc)
        return []


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
            missing_tables = get_missing_declared_tables(engine)
            if missing_tables:
                logger.warning(
                    "Database schema is missing declared tables %s. "
                    "Resetting database destructively and recreating from head.",
                    missing_tables,
                )
                reset_database_to_empty(engine)
                with engine.connect() as conn:
                    alembic_cfg.attributes["connection"] = conn
                    command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Automatic database upgrade failed: {e}")
        raise
