"""LanceDB provider 实现。

这个模块现在只负责纯 LanceDB 行为：
- 管理 LanceDB 连接缓存
- 对齐项目内部统一 `VectorStore` 抽象

provider 的“选哪一种后端”决策已经统一收口到 `factory.py`，
这里不再承担任何跨后端分流逻辑，避免出现：
- factory 说自己是统一入口
- 但某个 provider 内部又偷偷判断 backend

这种边界混乱会让后续维护者很难判断“问题到底该改哪一层”。
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

from ...config import get_lancedb_path, get_storage_root
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


def _matches_metadata_filters(
    metadata: Dict[str, Any],
    filters: Optional[Dict[str, Any]],
) -> bool:
    """判断 metadata 是否满足过滤条件。

    统一 provider 接口已经把过滤语义收口成 `dict[str, Any]`，
    但不同后端对 metadata 过滤的原生支持能力并不完全一致。

    因此这里显式提供一层最小公约数：
    - 所有后端至少支持 metadata 的精确相等匹配
    - 即使底层不能原生过滤，也保证业务层拿到一致结果
    """
    if not filters:
        return True

    for key, expected_value in filters.items():
        if metadata.get(key) != expected_value:
            return False
    return True


class LanceDBConnectionManager:
    """向量存储连接管理器。

    这里最重要的不是“如何连上 LanceDB”，而是：
    - 避免同一个目录被反复创建连接
    - 在连接长期不用后自动清理
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
            logger.info(
                "Using legacy LanceDB directory for LanceDB backend: %s",
                legacy_dir,
            )
            return str(legacy_dir)

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
                if hasattr(conn, "close"):
                    conn.close()
            except Exception as exc:
                logger.warning("Error closing expired connection for %s: %s", key, exc)

    def get_connection(self, db_dir: str) -> DBConnection:
        """按目录获取连接，并带缓存。"""
        if not db_dir:
            raise ValueError("LanceDB directory path must be non-empty")

        normalized = self._normalize_dirpath(db_dir)
        self._ensure_dir(normalized)

        current_time = time.time()

        with _cache_lock:
            self._cleanup_expired_connections()

            if normalized in _connection_cache:
                conn, last_accessed = _connection_cache[normalized]
                if not self._is_connection_expired(last_accessed):
                    _connection_cache[normalized] = (conn, current_time)
                    return conn
                _connection_cache.pop(normalized)

            conn = lancedb.connect(normalized)
            _connection_cache[normalized] = (conn, current_time)
            return conn

    def get_connection_from_env(self, env_var: str = "LANCEDB_DIR") -> DBConnection:
        """从环境变量推导连接目录，并返回连接。"""
        db_dir = os.getenv(env_var)

        if db_dir is None:
            if env_var == "LANCEDB_DIR":
                db_dir = self.get_default_lancedb_dir()
                logger.info(
                    "Using default LanceDB directory for LanceDB backend: %s",
                    db_dir,
                )
            else:
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
        """初始化统一向量存储实例。"""
        self._db_dir = db_dir
        self._collection_name = collection_name
        self._conn_manager = connection_manager or LanceDBConnectionManager()
        self._conn = self._conn_manager.get_connection(db_dir)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保向量表存在。"""
        try:
            self._conn.open_table(self._collection_name)
        except Exception as exc:
            logger.debug(
                "Table %s does not exist or open failed (%s), creating new table.",
                self._collection_name,
                exc,
            )
            sample_data = [
                {
                    "id": "sample",
                    "vector": [0.0, 0.0, 0.0],
                    "text": "sample",
                    "metadata": "{}",
                }
            ]
            table = self._conn.create_table(self._collection_name, data=sample_data)
            table.delete("id = 'sample'")

    def add_vectors(
        self,
        vectors: List[List[float]],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """批量写入向量。"""
        import json
        from uuid import uuid4

        if ids is None:
            ids = [str(uuid4()) for _ in vectors]

        if metadatas is None:
            metadatas = [{} for _ in vectors]

        data = []
        for index, vector in enumerate(vectors):
            data.append(
                {
                    "id": ids[index],
                    "vector": vector,
                    "text": metadatas[index].get("text", ""),
                    "metadata": json.dumps(metadatas[index], ensure_ascii=False),
                }
            )

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            # 对 LanceDB 来说，初始化阶段已经保证表存在。
            # 这里如果再次失败，通常说明底层目录损坏或连接异常，不应该静默改语义。
            self._ensure_table()
            table = self._conn.open_table(self._collection_name)
        table.add(data)
        return ids

    def delete_vectors(self, ids: List[str]) -> bool:
        """按 id 批量删除向量。"""
        if not ids:
            return True

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            # 对删除语义来说，“collection 还不存在”应视为幂等成功。
            return True

        try:
            id_conditions = " OR ".join([f"id = '{id_}'" for id_ in ids])
            table.delete(id_conditions)
            return True
        except Exception as exc:
            logger.error("Failed to delete vectors: %s", exc)
            return False

    def search_vectors(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """按查询向量检索相似记录。"""
        import json

        if top_k <= 0 or not query_vector:
            return []

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            return []

        search_limit = max(top_k, top_k * 5 if filters else top_k)
        results = (
            table.search(query_vector, vector_column_name="vector")
            .limit(search_limit)
            .to_pandas()
        )

        formatted_results = []
        for _, row in results.iterrows():
            try:
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            if not _matches_metadata_filters(metadata, filters):
                continue

            formatted_results.append(
                {
                    "id": row["id"],
                    "score": float(row["_distance"]) if "_distance" in row else 0.0,
                    "metadata": metadata,
                }
            )
            if len(formatted_results) >= top_k:
                break

        return formatted_results

    def clear(self) -> None:
        """清空当前 collection 中的全部向量与 metadata。"""
        try:
            table = self._conn.open_table(self._collection_name)
            table.delete("true")
        except Exception as exc:
            logger.error("Failed to clear vector store: %s", exc)
            self._ensure_table()

    def get_raw_connection(self) -> DBConnection:
        """返回底层原始连接。"""
        return self._conn


def get_connection(db_dir: str) -> DBConnection:
    """获取带缓存的向量存储连接。"""
    manager = LanceDBConnectionManager()
    return manager.get_connection(db_dir)


def get_connection_from_env(env_var: str = "LANCEDB_DIR") -> DBConnection:
    """从环境变量获取向量存储连接。"""
    manager = LanceDBConnectionManager()
    return manager.get_connection_from_env(env_var)
