import logging
from typing import Any, cast

from alembic import command
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from .config import create_alembic_config

logger = logging.getLogger(__name__)


# 已知历史遗留 revision 映射。
# 这些 revision 曾经出现在本地开发数据库里，但对应迁移文件已经被移除。
# 启动时如果直接 upgrade，Alembic 会因为找不到旧 revision 而中断。
# 这里显式把它们映射到当前保留迁移链上的合法锚点，再继续升级到 head。
LEGACY_REVISION_ALIASES: dict[str, str] = {
    "20260329_destructive_baseline_schema": "62ee04b26702",
}


def is_database_empty(engine: Engine) -> bool:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    return len(tables) == 0


def get_alembic_revision(engine: Engine) -> str | None:
    """Get the current Alembic revision from the database."""
    with engine.connect() as conn:
        context: Any = MigrationContext.configure(conn)
        return cast(str | None, context.get_current_revision())


def resolve_legacy_revision_alias(revision: str | None) -> str | None:
    """把已删除的历史 revision 映射到当前保留迁移链上的合法 revision。"""

    if revision is None:
        return None
    return LEGACY_REVISION_ALIASES.get(revision, revision)


def rewrite_legacy_revision_in_db(
    engine: Engine,
    *,
    from_revision: str,
    to_revision: str,
) -> None:
    """直接修正数据库 `alembic_version` 表中的已删除旧 revision。"""

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE alembic_version "
                "SET version_num = :to_revision "
                "WHERE version_num = :from_revision"
            ),
            {
                "to_revision": to_revision,
                "from_revision": from_revision,
            },
        )


def try_upgrade_db(engine: Engine) -> None:
    """Upgrade database to latest migration or stamp with base revision if unversioned."""
    try:
        logger.info("Starting database upgrade process")
        alembic_cfg = create_alembic_config(engine)
        version = get_alembic_revision(engine)

        if version is None:
            if is_database_empty(engine):
                # new database
                logger.info("Creating new database, stamping with latest revision.")
                with engine.connect() as conn:
                    alembic_cfg.attributes["connection"] = conn
                    command.stamp(alembic_cfg, "head")
            else:
                raise RuntimeError(
                    "Database exists without alembic revision information. Please initialize the database schema version manually by running: alembic stamp <revision>"
                )
        else:
            logger.info(f"Current version: {version}, upgrading to head")
            resolved_version = resolve_legacy_revision_alias(version)
            if resolved_version != version:
                logger.warning(
                    "Detected legacy Alembic revision %s, remapping to %s before upgrade",
                    version,
                    resolved_version,
                )
                rewrite_legacy_revision_in_db(
                    engine,
                    from_revision=version,
                    to_revision=resolved_version,
                )
            with engine.connect() as conn:
                alembic_cfg.attributes["connection"] = conn
                command.upgrade(alembic_cfg, "head")
    except Exception as e:
        logger.error(f"Automatic database upgrade failed: {e}")
        raise
