"""
LanceDB 向量存储实现，集成连接管理。

本模块提供 LanceDB 的连接管理和向量存储实现，
将原先分散在 lancedb_client.py 和独立向量存储实现中的功能合并到一起。
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
from ...core.tools.core.RAG_tools.LanceDB.schema_manager import _safe_close_table
from .base import VectorStore

logger = logging.getLogger(__name__)

__all__ = [
    "LanceDBConnectionManager",
    "LanceDBVectorStore",
    "clear_connection_cache",
    "get_connection",
    "get_connection_from_env",
]

# 连接缓存: key -> (connection, last_accessed_timestamp)
_connection_cache: Dict[str, Tuple[DBConnection, float]] = {}
_cache_lock = RLock()

# 连接 TTL（秒），默认 5 分钟
CONNECTION_TTL = int(os.getenv("LANCEDB_CONNECTION_TTL", "300"))


def clear_connection_cache() -> None:
    """清除全局 LanceDB 连接缓存。

    主要用于测试隔离，避免在不同 `LANCEDB_DIR` 值之间复用缓存的连接。
    """
    with _cache_lock:
        _connection_cache.clear()


class LanceDBConnectionManager:
    """
    LanceDB 连接管理器，支持缓存和自动清理。

    此类负责连接生命周期管理、缓存以及过期连接的自动清理。
    """

    @staticmethod
    def _normalize_dirpath(db_dir: str) -> str:
        """规范化数据库目录路径。"""
        return str(Path(db_dir).expanduser().resolve())

    @staticmethod
    def _ensure_dir(db_dir: str) -> None:
        """确保数据库目录存在。"""
        Path(db_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_connection_expired(last_accessed: float) -> bool:
        """检查连接是否已基于 TTL 过期。"""
        return time.time() - last_accessed > CONNECTION_TTL

    @staticmethod
    @functools.lru_cache(maxsize=None)
    def get_default_lancedb_dir() -> str:
        """获取默认的 LanceDB 目录路径。

        返回:
            默认 LanceDB 目录路径

        注意:
            优先级: legacy_location（如果包含数据）> ~/.xagent/data/lancedb
            首次调用后结果会被缓存。
        """
        # TODO: 此函数逻辑较混乱，存在潜在问题。
        #
        # 问题:
        # 1. get_lancedb_path() 默认返回相对路径 ("data/lancedb")，
        #    但可通过 LANCEDB_PATH 环境变量覆盖为任意绝对路径。
        #    将其同时用于 legacy_dir 和 new_dir 在语义上是错误的。
        #
        # 2. legacy_dir 将项目根目录与 get_lancedb_path() 组合，这意味着
        #    如果 LANCEDB_PATH 被设置为绝对路径，结果将是荒谬的。
        #
        # 3. 存在更广泛的不一致: LANCEDB_DIR 环境变量（其他地方使用）
        #    与 LANCEDB_PATH（config 模块使用）。参见 issue #252:
        #    https://github.com/xorbitsai/xagent/issues/252
        #
        # 正确的修复需要重构整个代码库中 LanceDB 路径的配置方式。
        # 目前暂时保持现有行为。
        #
        # 首先检查旧路径（项目根目录）以确保向后兼容
        legacy_dir = (
            Path(__file__).parent.parent.parent.parent.parent / get_lancedb_path()
        )
        if legacy_dir.is_dir() and list(legacy_dir.iterdir()):
            logger.info(f"Using legacy LanceDB location: {legacy_dir}")
            return str(legacy_dir)

        # 使用统一 config 模块的新默认路径
        # 注意: get_lancedb_path() 返回相对路径，因此与 get_storage_root() 组合得到绝对路径。
        # 前者为: new_dir = Path.home() / ".xagent" / "data" / "lancedb"
        new_dir = get_storage_root() / get_lancedb_path()
        new_dir.mkdir(parents=True, exist_ok=True)
        return str(new_dir)

    @staticmethod
    def _cleanup_expired_connections() -> None:
        """从缓存中移除过期连接。"""
        current_time = time.time()
        expired_keys = []

        for key, (conn, last_accessed) in _connection_cache.items():
            if current_time - last_accessed > CONNECTION_TTL:
                expired_keys.append(key)

        for key in expired_keys:
            conn, _ = _connection_cache.pop(key)
            try:
                # 如果连接有关闭方法，则关闭连接
                if hasattr(conn, "close"):
                    conn.close()
            except Exception as e:
                # 忽略连接清理过程中的错误，但记录日志
                logger.warning("Error closing expired connection for %s: %s", key, e)
                pass

    def get_connection(self, db_dir: str) -> DBConnection:
        """
        获取带缓存的 LanceDB 连接。

        参数:
            db_dir: 数据库目录路径

        返回:
            LanceDB 连接

        抛出:
            ValueError: 如果 db_dir 为空
        """
        if not db_dir:
            raise ValueError("LanceDB directory path must be non-empty")

        normalized = self._normalize_dirpath(db_dir)
        self._ensure_dir(normalized)

        current_time = time.time()

        with _cache_lock:
            # 清理过期连接
            self._cleanup_expired_connections()

            if normalized in _connection_cache:
                conn, last_accessed = _connection_cache[normalized]
                # 检查连接是否已过期
                if not self._is_connection_expired(last_accessed):
                    # 更新最后访问时间
                    _connection_cache[normalized] = (conn, current_time)
                    return conn
                else:
                    # 移除过期连接
                    _connection_cache.pop(normalized)

            # 创建新连接
            conn = lancedb.connect(normalized)
            _connection_cache[normalized] = (conn, current_time)
            return conn

    def get_connection_from_env(self, env_var: str = "LANCEDB_DIR") -> DBConnection:
        """
        从环境变量获取 LanceDB 连接，并在未设置时回退到默认路径。

        如果环境变量未设置，则使用 get_default_lancedb_dir()，该函数：
        1. 先检查旧路径（项目根目录 data/lancedb）是否包含数据
        2. 否则使用 ~/.xagent/data/lancedb

        参数:
            env_var: 包含数据库目录的环境变量名称

        返回:
            LanceDB 连接

        抛出:
            ValueError: 如果环境变量为空
            KeyError: 如果环境变量（除了 LANCEDB_DIR）未设置
        """
        db_dir = os.getenv(env_var)

        if db_dir is None:
            if env_var == "LANCEDB_DIR":
                # 仅在标准 LANCEDB_DIR 环境变量未设置时使用默认路径
                db_dir = self.get_default_lancedb_dir()
                logger.info(f"Using default LanceDB directory: {db_dir}")
            else:
                # 对于其他环境变量，继续抛出 KeyError
                raise KeyError(f"Environment variable {env_var} is not set")
        elif db_dir.strip() == "":
            raise ValueError(f"Environment variable {env_var} is empty")

        return self.get_connection(db_dir)


class LanceDBVectorStore(VectorStore):
    """
    LanceDB 向量存储实现。

    此类使用 LanceDB 作为后端存储引擎，实现了标准的 VectorStore 接口。
    """

    support_store_texts: ClassVar[bool] = True

    def __init__(
        self,
        db_dir: str,
        collection_name: str = "vectors",
        connection_manager: Optional[LanceDBConnectionManager] = None,
    ):
        """
        初始化 LanceDB 向量存储。

        参数:
            db_dir: 数据库目录路径
            collection_name: 向量的集合/表名
            connection_manager: 可选的连接管理器实例
        """
        self._db_dir = db_dir
        self._collection_name = collection_name
        self._conn_manager = connection_manager or LanceDBConnectionManager()
        self._conn = self._conn_manager.get_connection(db_dir)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保向量表存在。"""
        table = None
        try:
            table = self._conn.open_table(self._collection_name)
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
        finally:
            _safe_close_table(table)

    def add_vectors(
        self,
        vectors: List[List[float]],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        向存储中添加向量。

        参数:
            vectors: 要添加的向量列表
            ids: 每个向量对应的 ID 列表（可选）
            metadatas: 元数据字典列表（可选）

        返回:
            已存储的向量 ID 列表
        """
        import json
        from uuid import uuid4

        if ids is None:
            ids = [str(uuid4()) for _ in vectors]

        if metadatas is None:
            metadatas = [{} for _ in vectors]

        # 准备插入数据
        data = []
        for i, vector in enumerate(vectors):
            record = {
                "id": ids[i],
                "vector": vector,
                "text": metadatas[i].get("text", ""),
                "metadata": json.dumps(metadatas[i], ensure_ascii=False),
            }
            data.append(record)

        # 插入数据
        table = None
        try:
            table = self._conn.open_table(self._collection_name)
            table.add(data)
        finally:
            _safe_close_table(table)

        return ids

    def delete_vectors(self, ids: List[str]) -> bool:
        """
        按 ID 从存储中删除向量。

        参数:
            ids: 要删除的向量 ID 列表

        返回:
            删除成功返回 True
        """
        table = None
        try:
            table = self._conn.open_table(self._collection_name)

            # 构建删除条件
            id_conditions = " OR ".join([f"id = '{id_}'" for id_ in ids])
            table.delete(id_conditions)

            return True
        except Exception as e:
            logger.error("Failed to delete vectors: %s", e)
            return False
        finally:
            _safe_close_table(table)

    def search_vectors(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索与查询向量相似的向量。

        参数:
            query_vector: 用于搜索的向量
            top_k: 返回的最相似向量数量
            filters: 可选的元数据过滤条件

        返回:
            包含 id、score 和 metadata 的搜索结果列表
        """
        import json

        table = None
        try:
            table = self._conn.open_table(self._collection_name)

            # 执行向量搜索，显式指定向量列
            results = (
                table.search(query_vector, vector_column_name="vector")
                .limit(top_k)
                .to_pandas()
            )

            # 格式化结果
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
        finally:
            _safe_close_table(table)

    def clear(self) -> None:
        """清除存储中所有的向量和元数据。"""
        table = None
        try:
            # 尝试删除所有记录
            table = self._conn.open_table(self._collection_name)
            table.delete("true")  # Delete all records
        except Exception as e:
            logger.error("Failed to clear vector store: %s", e)
            # Table doesn't exist, just ensure it's created
            self._ensure_table()
        finally:
            _safe_close_table(table)

    def get_raw_connection(self) -> DBConnection:
        """获取原始 LanceDB 连接以进行高级操作。

        此方法提供对底层 LanceDB 连接的访问，用于超出标准 VectorStore 接口的操作。

        返回:
            原始 LanceDB 连接
        """
        return self._conn


# 便捷函数
def get_connection(db_dir: str) -> DBConnection:
    """获取带缓存的 LanceDB 连接。

    参数:
        db_dir: 数据库目录路径

    返回:
        LanceDB 连接
    """
    manager = LanceDBConnectionManager()
    return manager.get_connection(db_dir)


def get_connection_from_env(env_var: str = "LANCEDB_DIR") -> DBConnection:
    """从环境变量获取 LanceDB 连接，未设置 LANCEDB_DIR 时回退到默认路径。

    如果 LANCEDB_DIR 未设置，则使用 get_default_lancedb_dir()，
    该函数会先检查旧路径，然后回退到 ~/.xagent/data/lancedb。

    参数:
        env_var: 环境变量名称

    返回:
        LanceDB 连接
    """
    manager = LanceDBConnectionManager()
    return manager.get_connection_from_env(env_var)
