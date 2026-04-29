"""LanceDB 迁移：回填 chunks 和 embeddings 表中的 user_id 字段。

此迁移脚本通过关联 documents 表，回填 chunks 和 embeddings 表中的 user_id 字段
这是实现多租户数据隔离所必需的。

使用两阶段迁移：
- 阶段 1：正常回填，用保留哨兵值标记孤立记录
- 阶段 2：重试孤立记录，以防其父文档在迁期间并发创建
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
import tempfile
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lancedb.db import DBConnection

# 将父目录添加到路径以供导入
# 这必须在导入项目模块之前完成
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from xagent.core.tools.core.RAG_tools.core.config import MIN_INT64

# 路径修改后导入（独立迁移脚本需要）
# ruff: noqa: E402
from xagent.core.tools.core.RAG_tools.utils.lancedb_query_utils import (
    list_embeddings_table_names,
    query_to_list,
)
from xagent.core.tools.core.RAG_tools.utils.string_utils import escape_lancedb_string
from xagent.providers.vector_store.lancedb import get_connection_from_env

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 记录处理的批次大小，避免内存问题
BATCH_SIZE = 10000

# 孤立记录标记
# 使用为内部迁移状态保留的 int64 下限哨兵值。
# 这避免了与用户过滤语义（如未认证访问）的冲突。
ORPHANED_TEMPORARY = (
    MIN_INT64  # Phase 1: Temporary orphan (may be due to concurrent document creation)
)
ORPHANED_PERMANENT = (
    MIN_INT64 + 1
)  # Phase 2: Permanent orphan (confirmed no matching document exists)

# 全局锁，防止并发迁移
_migration_lock = threading.Lock()


def _ensure_table_exists(conn: DBConnection, table_name: str) -> None:
    """确保表存在，若不存在则使用默认 schema 创建。

    与 ensure_*_table 函数不同，此函数不验证 schema，允许
    迁移代码与旧 schema 表一起工作。
    """
    try:
        conn.open_table(table_name)
    except Exception:
        # 表不存在，使用默认 schema 创建
        if table_name == "chunks":
            import pyarrow as pa  # type: ignore

            schema = pa.schema(
                [
                    pa.field("collection", pa.string()),
                    pa.field("doc_id", pa.string()),
                    pa.field("parse_hash", pa.string()),
                    pa.field("chunk_id", pa.string()),
                    pa.field("index", pa.int32()),
                    pa.field("text", pa.large_string()),
                    pa.field("page_number", pa.int32()),
                    pa.field("section", pa.string()),
                    pa.field("anchor", pa.string()),
                    pa.field("json_path", pa.string()),
                    pa.field("chunk_hash", pa.string()),
                    pa.field("config_hash", pa.string()),
                    pa.field("created_at", pa.timestamp("us")),
                    pa.field("metadata", pa.string()),
                    pa.field("user_id", pa.int64()),
                ]
            )
            conn.create_table(table_name, schema=schema)
        elif table_name == "documents":
            import pyarrow as pa

            schema = pa.schema(
                [
                    pa.field("collection", pa.string()),
                    pa.field("doc_id", pa.string()),
                    pa.field("file_id", pa.string()),
                    pa.field("source_path", pa.string()),
                    pa.field("file_type", pa.string()),
                    pa.field("content_hash", pa.string()),
                    pa.field("uploaded_at", pa.timestamp("us")),
                    pa.field("title", pa.string()),
                    pa.field("language", pa.string()),
                    pa.field("user_id", pa.int64()),
                ]
            )
            conn.create_table(table_name, schema=schema)


def _get_migration_lock_file_path() -> str:
    """为跨进程迁移协调解析文件锁路径。"""
    lock_file = os.environ.get("LANCEDB_MIGRATION_LOCK_FILE")
    if lock_file:
        return lock_file

    lancedb_dir = os.environ.get("LANCEDB_DIR")
    if lancedb_dir:
        return os.path.join(lancedb_dir, ".lancedb_user_id_migration.lock")

    return os.path.join(
        tempfile.gettempdir(),
        "xagent_lancedb_user_id_migration.lock",
    )


def _acquire_file_lock() -> Any | None:
    """获取所有本地进程共享的非阻塞文件锁。"""
    lock_path = _get_migration_lock_file_path()
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock_file = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        return lock_file
    except BlockingIOError:
        lock_file.close()
        return None
    except Exception:
        lock_file.close()
        raise


def _release_file_lock(lock_file: Any) -> None:
    """安全释放文件锁并关闭文件句柄。"""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _orphaned_temporary_filter() -> str:
    """为 ORPHANED_TEMPORARY int64 哨兵值构建 LanceDB 安全的过滤条件。"""
    return f"user_id = cast({ORPHANED_TEMPORARY} as bigint)"


def _build_doc_id_in_filter(doc_ids: list[str]) -> str:
    """为 doc_id 值构建安全的 LanceDB IN 过滤条件。"""
    escaped_ids = [f"'{escape_lancedb_string(doc_id)}'" for doc_id in doc_ids]
    return f"doc_id IN ({', '.join(escaped_ids)})"


def _build_record_update_filter(
    record: dict[str, Any], filter_fields: list[str]
) -> str:
    """通过关键字段构建定位单条记录的安全 AND 过滤条件。"""
    filter_parts: list[str] = []
    for field_name in filter_fields:
        field_value = record.get(field_name)
        if field_value is None:
            filter_parts.append(f"{field_name} IS NULL")
            continue

        # 数值比较不加引号；对其他标量值加引号并转义。
        if isinstance(field_value, (int, float)) and not isinstance(field_value, bool):
            filter_parts.append(f"{field_name} = {field_value}")
        else:
            escaped_value = escape_lancedb_string(field_value)
            filter_parts.append(f"{field_name} = '{escaped_value}'")
    return " and ".join(filter_parts)


def _remap_legacy_orphaned_user_ids(conn: DBConnection, dry_run: bool = False) -> dict:
    """对旧版孤立标记值进行一次性兼容性重映射。

    历史迁移运行使用 ``-1`` 作为临时孤立标记，现在
    与未认证用户的读取过滤语义冲突。此辅助函数将旧版
    ``-1`` 重映射到保留的 int64 哨兵值，以保持升级后
    阶段 2 重试行为的一致性。
    """

    remapped_counts: dict[str, int] = {}
    target_tables = ["chunks", *_get_embeddings_tables(conn)]

    for table_name in target_tables:
        try:
            table = conn.open_table(table_name)
        except Exception as exc:
            logger.warning("Skip legacy remap for %s: %s", table_name, exc)
            continue

        try:
            legacy_rows = query_to_list(
                table.search().where("user_id = -1").limit(BATCH_SIZE)
            )
            if not legacy_rows:
                continue

            remapped_counts[table_name] = len(legacy_rows)
            if dry_run:
                logger.info(
                    "Dry-run legacy remap: %s rows in %s would be updated from -1 to %s",
                    len(legacy_rows),
                    table_name,
                    ORPHANED_TEMPORARY,
                )
                continue

            table.update("user_id = -1", {"user_id": ORPHANED_TEMPORARY})
            logger.info(
                "Legacy remap complete: %s rows in %s updated from -1 to %s",
                len(legacy_rows),
                table_name,
                ORPHANED_TEMPORARY,
            )
        except Exception as exc:
            logger.warning("Legacy remap failed for %s: %s", table_name, exc)

    return remapped_counts


def _backfill_table_core(
    table: Any,
    docs_table: Any,
    query_filter: str,
    filter_fields: list[str],
    failure_user_id: int,
    dry_run: bool,
    log_prefix: str = "",
) -> dict:
    """回填单张表的核心逻辑。

    参数：
        table：要回填的 LanceDB 表
        docs_table：用于查找的 Documents 表
        query_filter：查找需要回填的记录的过滤条件（如 "user_id IS NULL"）
        filter_fields：用于标识特定更新记录的字段
        failure_user_id：文档查找失败时设置的 user_id（如 -1 或 -2）
        dry_run：为 True 时不进行实际修改
        log_prefix：日志消息的前缀

    返回：
        包含统计信息的字典
    """
    total_backfilled = 0
    total_skipped = 0
    total_failed = 0
    batch_number = 0

    while True:
        # 获取匹配过滤条件的一批记录
        batch = query_to_list(table.search().where(query_filter).limit(BATCH_SIZE))

        if not batch:
            break

        batch_number += 1
        logger.info(
            f"{log_prefix} Processing batch #{batch_number}: {len(batch)} records..."
        )

        # 从 documents 表构建 doc_id -> user_id 映射
        doc_user_map = {}
        all_doc_ids = [
            doc_id for doc_id in set(r.get("doc_id") for r in batch) if doc_id
        ]

        if all_doc_ids:
            # 批量查找文档
            docs = query_to_list(
                docs_table.search()
                .where(_build_doc_id_in_filter(all_doc_ids))
                .limit(len(all_doc_ids))
            )
            for doc in docs:
                if doc.get("user_id") is not None:
                    doc_user_map[doc.get("doc_id")] = doc.get("user_id")

        logger.info(
            f"{log_prefix} Batch #{batch_number}: Found user_id for {len(doc_user_map)} / {len(all_doc_ids)} documents"
        )

        # 更新记录
        skipped = 0
        updated_in_batch = 0
        for record in batch:
            doc_id = record.get("doc_id")

            if doc_id in doc_user_map:
                user_id = doc_user_map[doc_id]
                is_recovered = True
            else:
                user_id = failure_user_id
                is_recovered = False
                skipped += 1
                total_skipped += 1

            if not dry_run:
                try:
                    # 构建更新过滤条件
                    update_filter = _build_record_update_filter(record, filter_fields)
                    table.update(update_filter, {"user_id": user_id})
                    updated_in_batch += 1

                    if is_recovered:
                        total_backfilled += 1
                except Exception as e:
                    total_failed += 1
                    logger.warning(f"{log_prefix} Failed to update record: {e}")
            else:
                if is_recovered:
                    total_backfilled += 1

        logger.info(
            f"{log_prefix} Batch #{batch_number}: {len(batch) - skipped} processed, {skipped} marked as failure_id ({failure_user_id})"
        )
        if dry_run:
            # 干运行不修改记录，因此处理额外的批次将
            # 反复读取相同的记录且永远不会收敛。
            break
        if updated_in_batch == 0:
            logger.error(
                "%s Batch #%s made zero update progress; aborting to avoid infinite loop.",
                log_prefix,
                batch_number,
            )
            break

    return {
        "total": total_backfilled + total_skipped + total_failed,
        "backfilled": total_backfilled,
        "skipped": total_skipped,
        "failed": total_failed,
    }


def backfill_chunks_table(
    dry_run: bool = False, conn: DBConnection | None = None
) -> dict:
    """回填 chunks 表的 user_id（阶段 1）。"""
    if conn is None:
        conn = get_connection_from_env()

    # 对于迁移，即使表有旧 schema 也需要使用它们
    # 不要使用 ensure_chunks_table，因为它验证 schema 会在旧表上失败
    _ensure_table_exists(conn, "chunks")
    _ensure_table_exists(conn, "documents")

    chunks_table = conn.open_table("chunks")
    docs_table = conn.open_table("documents")

    logger.info("Phase 1: Starting chunks table user_id backfill...")
    result = _backfill_table_core(
        table=chunks_table,
        docs_table=docs_table,
        query_filter="user_id IS NULL",
        filter_fields=["doc_id", "chunk_id", "parse_hash"],
        failure_user_id=ORPHANED_TEMPORARY,
        dry_run=dry_run,
        log_prefix="Chunks Phase 1:",
    )
    result["table"] = "chunks"
    return result


def backfill_orphaned_chunks(
    dry_run: bool = False, conn: DBConnection | None = None
) -> dict:
    """重试孤立 chunks 的回填（阶段 2）。"""
    if conn is None:
        conn = get_connection_from_env()

    # 对于迁移，即使表有旧 schema 也需要使用它们
    _ensure_table_exists(conn, "chunks")
    _ensure_table_exists(conn, "documents")

    chunks_table = conn.open_table("chunks")
    docs_table = conn.open_table("documents")

    logger.info("Phase 2: Retrying orphaned chunks (user_id = ORPHANED_TEMPORARY)...")
    result = _backfill_table_core(
        table=chunks_table,
        docs_table=docs_table,
        query_filter=_orphaned_temporary_filter(),
        filter_fields=["doc_id", "chunk_id", "parse_hash"],
        failure_user_id=ORPHANED_PERMANENT,
        dry_run=dry_run,
        log_prefix="Chunks Phase 2:",
    )
    result["table"] = "chunks"
    return result


def _get_embeddings_tables(conn: DBConnection) -> list[str]:
    """获取所有 embeddings 表（API 兼容）的辅助函数。"""
    try:
        return list_embeddings_table_names(conn)
    except Exception as e:
        logger.warning(f"Failed to list LanceDB tables: {e}")
        return []


def backfill_embeddings_table(
    dry_run: bool = False, conn: DBConnection | None = None
) -> dict:
    """回填 embeddings 表的 user_id（阶段 1）。"""
    if conn is None:
        conn = get_connection_from_env()

    _ensure_table_exists(conn, "documents")
    embeddings_tables = _get_embeddings_tables(conn)

    if not embeddings_tables:
        return {
            "table": "embeddings",
            "total": 0,
            "backfilled": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

    docs_table = conn.open_table("documents")
    all_results = []

    for table_name in embeddings_tables:
        logger.info(f"Phase 1: Processing {table_name}...")
        res = _backfill_table_core(
            table=conn.open_table(table_name),
            docs_table=docs_table,
            query_filter="user_id IS NULL",
            filter_fields=["doc_id", "chunk_id", "parse_hash", "model"],
            failure_user_id=ORPHANED_TEMPORARY,
            dry_run=dry_run,
            log_prefix=f"Embeddings Phase 1 ({table_name}):",
        )
        res["table"] = table_name
        all_results.append(res)

    return {
        "table": "embeddings",
        "total": sum(r["total"] for r in all_results),
        "backfilled": sum(r["backfilled"] for r in all_results),
        "skipped": sum(r["skipped"] for r in all_results),
        "failed": sum(r["failed"] for r in all_results),
        "details": all_results,
    }


def backfill_orphaned_embeddings(
    dry_run: bool = False, conn: DBConnection | None = None
) -> dict:
    """重试孤立 embeddings 的回填（阶段 2）。"""
    if conn is None:
        conn = get_connection_from_env()

    _ensure_table_exists(conn, "documents")

    embeddings_tables = _get_embeddings_tables(conn)
    if not embeddings_tables:
        return {
            "table": "embeddings",
            "total": 0,
            "backfilled": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

    docs_table = conn.open_table("documents")
    all_results = []

    for table_name in embeddings_tables:
        logger.info(f"Phase 2: Processing {table_name}...")
        res = _backfill_table_core(
            table=conn.open_table(table_name),
            docs_table=docs_table,
            query_filter=_orphaned_temporary_filter(),
            filter_fields=["doc_id", "chunk_id", "parse_hash", "model"],
            failure_user_id=ORPHANED_PERMANENT,
            dry_run=dry_run,
            log_prefix=f"Embeddings Phase 2 ({table_name}):",
        )
        res["table"] = table_name
        all_results.append(res)

    return {
        "table": "embeddings",
        "total": sum(r["total"] for r in all_results),
        "backfilled": sum(r["backfilled"] for r in all_results),
        "skipped": sum(r["skipped"] for r in all_results),
        "failed": sum(r["failed"] for r in all_results),
        "details": all_results,
    }


def backfill_all(dry_run: bool = False, conn: DBConnection | None = None) -> dict:
    """对所有表运行完整的双阶段回填。"""
    if conn is None:
        conn = get_connection_from_env()

    if not _migration_lock.acquire(blocking=False):
        logger.warning("Another migration is already in progress")
        return {"error": "Migration lock already held"}

    file_lock = None
    try:
        file_lock = _acquire_file_lock()
        if file_lock is None:
            logger.warning("Another migration is running in a different process")
            return {"error": "Migration file lock already held"}

        logger.info("=" * 60)
        logger.info("LanceDB User ID Backfill Migration (Two-Phase)")
        logger.info("=" * 60)

        legacy_remap = _remap_legacy_orphaned_user_ids(conn=conn, dry_run=dry_run)
        if legacy_remap:
            logger.info("Legacy orphan remap summary: %s", legacy_remap)
        has_legacy_chunk_orphans = legacy_remap.get("chunks", 0) > 0
        has_legacy_embedding_orphans = any(
            table_name.startswith("embeddings_") and count > 0
            for table_name, count in legacy_remap.items()
        )

        # Phase 1
        chunks_res = backfill_chunks_table(dry_run=dry_run, conn=conn)
        embeddings_res = backfill_embeddings_table(dry_run=dry_run, conn=conn)

        # Phase 2
        chunks_retry = {"backfilled": 0, "skipped": chunks_res["skipped"]}
        embeddings_retry = {"backfilled": 0, "skipped": embeddings_res["skipped"]}

        if chunks_res["skipped"] > 0 or has_legacy_chunk_orphans:
            chunks_retry = backfill_orphaned_chunks(dry_run=dry_run, conn=conn)
            chunks_res["backfilled"] += chunks_retry["backfilled"]
            chunks_res["skipped"] = chunks_retry["skipped"]
            chunks_res["failed"] += chunks_retry["failed"]

        if embeddings_res["skipped"] > 0 or has_legacy_embedding_orphans:
            embeddings_retry = backfill_orphaned_embeddings(dry_run=dry_run, conn=conn)
            embeddings_res["backfilled"] += embeddings_retry["backfilled"]
            embeddings_res["skipped"] = embeddings_retry["skipped"]
            embeddings_res["failed"] += embeddings_retry["failed"]

        return {
            "chunks": chunks_res,
            "embeddings": embeddings_res,
            "locked": True,
        }
    finally:
        if file_lock is not None:
            _release_file_lock(file_lock)
        _migration_lock.release()
        logger.info("Migration lock released")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill user_id for LanceDB tables for multi-tenancy support.\n\n"
        "This script performs a two-phase migration:\n"
        f"  Phase 1: Backfill records, mark orphaned records with user_id = {ORPHANED_TEMPORARY}\n"
        f"  Phase 2: Retry orphaned records, mark permanent orphans with user_id = {ORPHANED_PERMANENT}\n\n"
        "Orphaned records occur when chunks/embeddings exist without matching documents,\n"
        "which can happen due to concurrent document creation during migration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration without making actual changes",
    )
    parser.add_argument(
        "--chunks-only",
        action="store_true",
        help="Only backfill chunks table (skip embeddings tables)",
    )
    parser.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Only backfill embeddings tables (skip chunks table)",
    )
    args = parser.parse_args()

    try:
        if args.chunks_only:
            result = backfill_chunks_table(dry_run=args.dry_run)
        elif args.embeddings_only:
            result = backfill_embeddings_table(dry_run=args.dry_run)
        else:
            result = backfill_all(dry_run=args.dry_run)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(2)
