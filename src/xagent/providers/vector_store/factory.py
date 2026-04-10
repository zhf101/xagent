"""统一向量 provider 工厂。

业务层应该只依赖 `VectorStore` 抽象与这个工厂，
而不应该再自己判断当前到底使用哪一种向量后端。
"""

from __future__ import annotations

from .base import VectorStore
from .lancedb import LanceDBConnectionManager, LanceDBVectorStore
from .pgvector import PGVectorVectorStore
from ...config import (
    get_vector_backend,
    get_vector_milvus_db_name,
    get_vector_milvus_token,
    get_vector_milvus_uri,
)


def create_vector_store(
    collection_name: str,
    *,
    backend: str | None = None,
    db_dir: str | None = None,
) -> VectorStore:
    """按当前配置创建统一 `VectorStore` 实例。"""
    normalized_backend = str(backend or get_vector_backend()).strip().lower() or "lancedb"

    if normalized_backend == "lancedb":
        resolved_db_dir = db_dir or LanceDBConnectionManager.get_default_lancedb_dir()
        return LanceDBVectorStore(
            db_dir=resolved_db_dir,
            collection_name=collection_name,
        )

    if normalized_backend == "pgvector":
        return PGVectorVectorStore(
            db_dir=db_dir,
            collection_name=collection_name,
        )

    if normalized_backend == "milvus":
        from .milvus import MilvusVectorStore

        return MilvusVectorStore(
            uri=get_vector_milvus_uri(),
            collection_name=collection_name,
            token=get_vector_milvus_token(),
            db_name=get_vector_milvus_db_name(),
        )

    raise ValueError(
        f"Unsupported vector backend: {normalized_backend}. "
        "Expected one of: lancedb, pgvector, milvus"
    )
