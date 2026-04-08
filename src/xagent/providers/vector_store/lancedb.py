"""LanceDB / pgvector 向量存储统一入口。

这个模块原本只服务 LanceDB，但当前分支为了让上层调用点尽量不改 import，
把“连接管理兼容层”也收口到了这里：
- 当向量后端仍是 LanceDB，走原生 LanceDB 连接
- 当向量后端切到 pgvector，仍然从这里返回兼容连接包装

因此它现在承担的是“统一向量存储入口”职责，而不只是一个单纯的 LanceDB client。
"""

from __future__ import annotations

import functools
import logging
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any, ClassVar, Dict, List, Optional, Tuple

import lancedb
from lancedb.db import DBConnection

from ...config import get_lancedb_path, get_storage_root, get_vector_backend
from .pgvector import PGVectorConnectionManager
from .base import VectorStore

logger = logging.getLogger(__name__)

__all__ = [
    "LanceDBConnectionManager",
    "LanceDBVectorStore",
    "get_connection",
    "get_connection_from_env",
]

# Connection cache: key -> (connection, last_accessed_timestamp)
_connection_cache: Dict[str, Tuple[DBConnection, float]] = {}
_cache_lock = RLock()

# Connection TTL (seconds), default 5 minutes
CONNECTION_TTL = int(os.getenv("LANCEDB_CONNECTION_TTL", "300"))


def _build_vector_table_missing_message(collection_name: str) -> str:
    """统一返回 pgvector 缺表时的指引文案。

    当前项目已经转向 SQL-first 数据库治理，所以 pgvector 模式下如果缺表，
    不能再像 LanceDB 一样由运行时自动补建；必须回到 SQL 脚本补齐。
    """
    return (
        f"Vector table '{collection_name}' does not exist in pgvector backend. "
        "Please initialize it via db/postgresql/init.sql or add a patch under "
        "db/postgresql/patches before writing vector data."
    )


class LanceDBConnectionManager:
    """向量存储连接管理器。

    这里最重要的不是“如何连上 LanceDB”，而是：
    - 避免同一个目录被反复创建连接
    - 在连接长期不用后自动清理
    - 在切到 pgvector 时保持同一入口不变
    """

    @staticmethod
    def _normalize_dirpath(db_dir: str) -> str:
        """把目录路径规范成绝对路径，避免缓存键因相对路径差异失效。"""
        return str(Path(db_dir).expanduser().resolve())

    @staticmethod
    def _ensure_dir(db_dir: str) -> None:
        """确保目录存在。"""
        Path(db_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_connection_expired(last_accessed: float) -> bool:
        """判断缓存连接是否超出 TTL。"""
        return time.time() - last_accessed > CONNECTION_TTL

    @staticmethod
    @functools.lru_cache(maxsize=None)
    def get_default_lancedb_dir() -> str:
        """Get the default LanceDB directory path.

        Returns:
            Default LanceDB directory path

        Note:
            Priority: legacy_location (if has data) > ~/.xagent/data/lancedb
            Result is cached after first call.
        """
        # TODO: This function has confusing logic and potential issues.
        #
        # Problems:
        # 1. get_lancedb_path() returns a relative path by default ("data/lancedb"),
        #    but can be overridden by LANCEDB_PATH env var to any absolute path.
        #    Using it for both legacy_dir and new_dir is semantically wrong.
        #
        # 2. legacy_dir combines project root with get_lancedb_path(), which means
        #    if LANCEDB_PATH is set to an absolute path, the result is nonsensical.
        #
        # 3. There's a broader inconsistency: LANCEDB_DIR env var (used elsewhere)
        #    vs LANCEDB_PATH (used by config module). See issue #252:
        #    https://github.com/xorbitsai/xagent/issues/252
        #
        # The proper fix requires refactoring how LanceDB paths are configured
        # across the codebase. For now, keep the existing behavior.
        #
        # Check legacy location (project root) first for backward compatibility
        legacy_dir = (
            Path(__file__).parent.parent.parent.parent.parent / get_lancedb_path()
        )
        if legacy_dir.is_dir() and list(legacy_dir.iterdir()):
            logger.info(f"Using legacy LanceDB location: {legacy_dir}")
            return str(legacy_dir)

        # Use new default location from unified config module
        # Note: get_lancedb_path() returns relative path, so we combine with
        # get_storage_root() to get absolute path.
        # The former is: new_dir = Path.home() / ".xagent" / "data" / "lancedb"
        new_dir = get_storage_root() / get_lancedb_path()
        new_dir.mkdir(parents=True, exist_ok=True)
        return str(new_dir)

    @staticmethod
    def _cleanup_expired_connections() -> None:
        """Remove expired connections from cache."""
        current_time = time.time()
        expired_keys = []

        for key, (conn, last_accessed) in _connection_cache.items():
            if current_time - last_accessed > CONNECTION_TTL:
                expired_keys.append(key)

        for key in expired_keys:
            conn, _ = _connection_cache.pop(key)
            try:
                # Close connection if it has a close method
                if hasattr(conn, "close"):
                    conn.close()
            except Exception as e:
                # Ignore errors during connection cleanup but log them
                logger.warning("Error closing expired connection for %s: %s", key, e)
                pass

    def get_connection(self, db_dir: str) -> DBConnection:
        """按目录获取连接，并带缓存。

        对上层来说，这里返回的是“当前向量后端可用连接”；
        至于是 LanceDB 还是 pgvector，调用方不应该感知太多底层差异。
        """
        # 兼容模式：当向量后端切到 pgvector 时，
        # 这里直接返回 pgvector 连接包装，让上层调用点不必改 import。
        if get_vector_backend() == "pgvector":
            return PGVectorConnectionManager().get_connection(db_dir)  # type: ignore[return-value]

        if not db_dir:
            raise ValueError("LanceDB directory path must be non-empty")

        normalized = self._normalize_dirpath(db_dir)
        self._ensure_dir(normalized)

        current_time = time.time()

        with _cache_lock:
            # Cleanup expired connections
            self._cleanup_expired_connections()

            if normalized in _connection_cache:
                conn, last_accessed = _connection_cache[normalized]
                # Check if connection is expired
                if not self._is_connection_expired(last_accessed):
                    # Update last access time
                    _connection_cache[normalized] = (conn, current_time)
                    return conn
                else:
                    # Remove expired connection
                    _connection_cache.pop(normalized)

            # Create new connection
            conn = lancedb.connect(normalized)
            _connection_cache[normalized] = (conn, current_time)
            return conn

    def get_connection_from_env(self, env_var: str = "LANCEDB_DIR") -> DBConnection:
        """从环境变量推导连接目录，并返回连接。

        这里保留了对历史 `LANCEDB_DIR` 语义的兼容：
        标准变量缺失时可回退到默认目录；非标准变量缺失则直接报错。
        """
        if get_vector_backend() == "pgvector":
            return PGVectorConnectionManager().get_connection_from_env(env_var)  # type: ignore[return-value]

        db_dir = os.getenv(env_var)

        if db_dir is None:
            if env_var == "LANCEDB_DIR":
                # Use default path only for the standard LANCEDB_DIR environment variable
                db_dir = self.get_default_lancedb_dir()
                logger.info(f"Using default LanceDB directory: {db_dir}")
            else:
                # For other environment variables, raise KeyError as before
                raise KeyError(f"Environment variable {env_var} is not set")
        elif db_dir.strip() == "":
            raise ValueError(f"Environment variable {env_var} is empty")

        return self.get_connection(db_dir)


class LanceDBVectorStore(VectorStore):
    """LanceDB 向量存储实现。

    这个类负责对齐项目内部统一的 `VectorStore` 接口，
    让上层 RAG / memory 代码不需要直接依赖 LanceDB SDK。
    """

    support_store_texts: ClassVar[bool] = True

    def __init__(
        self,
        db_dir: str,
        collection_name: str = "vectors",
        connection_manager: Optional[LanceDBConnectionManager] = None,
    ):
        """初始化统一向量存储实例。

        即使类名仍叫 `LanceDBVectorStore`，当前也承担了 pgvector 兼容入口职责，
        调用方不应该依赖它的具体底层实现。
        """
        self._db_dir = db_dir
        self._collection_name = collection_name
        self._conn_manager = connection_manager or LanceDBConnectionManager()
        self._conn = self._conn_manager.get_connection(db_dir)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保向量表存在。

        LanceDB 与 pgvector 的建表时机不同，因此这里必须区分处理：
        - LanceDB 可以用 sample row 预建表
        - pgvector 需要等真实向量维度已知后再建表
        """
        if get_vector_backend() == "pgvector":
            # pgvector 需要根据首批向量维度建表，不能像 LanceDB 一样
            # 用固定 3 维 sample vector 预建表；否则后续真实向量写入会维度冲突。
            try:
                self._conn.open_table(self._collection_name)
            except Exception:
                logger.debug(
                    "pgvector backend defers table creation for %s until first write.",
                    self._collection_name,
                )
            return

        try:
            self._conn.open_table(self._collection_name)
        except Exception as e:
            logger.debug(
                "Table %s does not exist or open failed (%s), creating new table.",
                self._collection_name,
                e,
            )
            # Table doesn't exist, create it with sample data
            # LanceDB needs actual data to properly infer vector column type
            sample_data = [
                {
                    "id": "sample",
                    "vector": [0.0, 0.0, 0.0],  # Sample vector
                    "text": "sample",
                    "metadata": "{}",
                }
            ]
            table = self._conn.create_table(self._collection_name, data=sample_data)
            # Remove sample data
            table.delete("id = 'sample'")

    def add_vectors(
        self,
        vectors: List[List[float]],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """批量写入向量。

        这里统一把 metadata 折叠成 JSON 文本，保证 LanceDB / pgvector 两个后端
        都能以相近的数据形状落库。
        """
        import json
        from uuid import uuid4

        if ids is None:
            ids = [str(uuid4()) for _ in vectors]

        if metadatas is None:
            metadatas = [{} for _ in vectors]

        # Prepare data for insertion
        data = []
        for i, vector in enumerate(vectors):
            record = {
                "id": ids[i],
                "vector": vector,
                "text": metadatas[i].get("text", ""),
                "metadata": json.dumps(metadatas[i], ensure_ascii=False),
            }
            data.append(record)

        # Insert data
        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            if get_vector_backend() == "pgvector":
                raise RuntimeError(
                    _build_vector_table_missing_message(self._collection_name)
                )
            # LanceDB 仍保留“首次写入自动建表”的旧行为。
            table = self._conn.create_table(self._collection_name, data=data)
        table.add(data)

        return ids

    def delete_vectors(self, ids: List[str]) -> bool:
        """按 id 批量删除向量。"""
        try:
            table = self._conn.open_table(self._collection_name)

            # Build delete condition
            id_conditions = " OR ".join([f"id = '{id_}'" for id_ in ids])
            table.delete(id_conditions)

            return True
        except Exception as e:
            logger.error("Failed to delete vectors: %s", e)
            return False

    def search_vectors(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """按查询向量检索相似记录。

        返回值统一整理成 `id + score + metadata`，方便上层 RAG / memory
        在不感知底层数据库差异的情况下继续编排。
        """
        import json

        table = self._conn.open_table(self._collection_name)

        # Perform vector search, explicitly specify vector column
        results = (
            table.search(query_vector, vector_column_name="vector")
            .limit(top_k)
            .to_pandas()
        )

        # Format results
        formatted_results = []
        for _, row in results.iterrows():
            try:
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            result = {
                "id": row["id"],
                "score": float(row["_distance"]) if "_distance" in row else 0.0,
                "metadata": metadata,
            }
            formatted_results.append(result)

        return formatted_results

    def clear(self) -> None:
        """清空当前 collection 中的全部向量与 metadata。"""
        try:
            # Try to delete all records
            table = self._conn.open_table(self._collection_name)
            table.delete("true")  # Delete all records
        except Exception as e:
            logger.error("Failed to clear vector store: %s", e)
            # Table doesn't exist, just ensure it's created
            self._ensure_table()

    def get_raw_connection(self) -> DBConnection:
        """返回底层原始连接。

        这个出口只给少数需要越过 `VectorStore` 抽象层的场景使用，
        例如 memory store 需要直接操作 table schema。
        """
        return self._conn


# Convenience functions
def get_connection(db_dir: str) -> DBConnection:
    """获取带缓存的向量存储连接。"""
    manager = LanceDBConnectionManager()
    return manager.get_connection(db_dir)


def get_connection_from_env(env_var: str = "LANCEDB_DIR") -> DBConnection:
    """从环境变量获取向量存储连接。

    对标准 `LANCEDB_DIR` 会带默认路径兜底；其他变量名仍保持“未设置即报错”的旧语义。
    """
    manager = LanceDBConnectionManager()
    return manager.get_connection_from_env(env_var)
