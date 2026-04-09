"""Memory utilities for web application."""
"""Memory utilities for web application.
Web 层使用的记忆辅助函数。
1. 为 Web 应用创建合适的 memory store（LanceDB 或内存版）。
2. 把底层 MemoryNote / MemoryBundle 序列化成前端更容易消费的 JSON 结构。
"""

import logging
import os
from typing import Optional, Union
from datetime import datetime
from typing import Any, Optional, Union

from xagent.core.memory.core import MemoryNote
from xagent.core.memory.freshness import get_freshness_label
from xagent.core.memory.in_memory import InMemoryMemoryStore
from xagent.core.memory.lancedb import LanceDBMemoryStore
from xagent.core.memory.prompt_builder import build_memory_prompt_sections
from xagent.core.memory.retriever import MemoryBundle

from .user_isolated_memory import UserIsolatedMemoryStore

logger = logging.getLogger(__name__)

# Type alias for our memory store types that includes user isolation
MemoryStoreType = Union[
    InMemoryMemoryStore, LanceDBMemoryStore, UserIsolatedMemoryStore
]


def create_memory_store(
    similarity_threshold: Optional[float] = None,
) -> MemoryStoreType:
    """Create memory store based on available embedding models
    根据当前模型配置创建记忆存储实现。

    Args:
        similarity_threshold: Optional similarity threshold for vector search.
                           If not provided, uses environment variable or default value.
    """
    # Get similarity threshold from parameter, environment variable, or default
    if similarity_threshold is None:
        similarity_threshold = float(os.getenv("MEMORY_SIMILARITY_THRESHOLD", "1.5"))

    logger.info(f"Using similarity threshold: {similarity_threshold}")

    try:
        # Check if there's a default embedding model in database
        # Web 层这里不会硬编码 embedding 配置，
        # 而是读取数据库里当前可用的 embedding model 配置来决定是否启用向量检索。
        from sqlalchemy import create_engine
        from sqlalchemy.ext.declarative import declarative_base
        from sqlalchemy.orm import sessionmaker

        from ..core.model import EmbeddingModelConfig
        from ..core.model.storage.db.adapter import SQLAlchemyModelHub
        from ..core.model.storage.db.db_models import create_model_table
        from ..core.storage.manager import get_default_db_url

        # Create database engine
        database_url = get_default_db_url()
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False}
            if "sqlite" in database_url
            else {},
        )
        # Create session factory
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        # Create base model class
        Base = declarative_base()
        Model = create_model_table(Base)
        db = SessionLocal()
        Base.metadata.create_all(engine)

        hub = SQLAlchemyModelHub(db, Model)
        try:
            all_models = hub.list().values()
            embedding_model = next(
                (x for x in all_models if isinstance(x, EmbeddingModelConfig)), None
            )

            if embedding_model:
                # Create LanceDB store with embedding model
                # 有 embedding 模型时，优先启用 LanceDB，支持向量搜索。
                from xagent.core.model.embedding import create_embedding_adapter

                current_dir = os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                )
                db_dir = os.path.join(current_dir, "memory_store")

                lancedb_store = LanceDBMemoryStore(
                    db_dir=db_dir,
                    embedding_model=create_embedding_adapter(embedding_model),
                    similarity_threshold=similarity_threshold,
                )
                # Wrap with user isolation for web application
                # Web 侧必须套一层用户隔离，避免不同用户共享记忆空间。
                logger.info("Wrapping LanceDB store with user isolation")
                return UserIsolatedMemoryStore(lancedb_store)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error checking for embedding model: {e}")

    # Default to in-memory store
    # 如果没有配置 embedding，就退化到纯内存实现。
    # 这样系统仍然能跑，只是没有向量检索能力。
    logger.info("Using in-memory store")
    in_memory_store = InMemoryMemoryStore()

    # Wrap with user isolation for web application
    logger.info("Wrapping with user isolation")
    return UserIsolatedMemoryStore(in_memory_store)


def serialize_memory_note(memory: MemoryNote) -> dict[str, Any]:
    """把底层 MemoryNote 转成 API 响应字典。"""
    freshness_label = _get_freshness_label(memory)
    return {
        "id": memory.id,
        "content": memory.content,
        "keywords": memory.keywords,
        "tags": memory.tags,
        "category": memory.category,
        "memory_type": memory.memory_type,
        "memory_subtype": memory.memory_subtype,
        "scope": memory.scope,
        "timestamp": memory.timestamp,
        "mime_type": memory.mime_type,
        "source_session_id": memory.source_session_id,
        "source_agent_id": memory.source_agent_id,
        "project_id": memory.project_id,
        "workspace_id": memory.workspace_id,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "freshness_at": memory.freshness_at,
        "freshness_label": freshness_label,
        "expires_at": memory.expires_at,
        "dedupe_key": memory.dedupe_key,
        "status": memory.status,
        "metadata": memory.metadata,
    }


def serialize_memory_bundle(bundle: MemoryBundle) -> dict[str, Any]:
    """把结构化 bundle 转成前端调试和接口展示都能直接用的格式。"""
    return {
        "session_context": bundle.session_context,
        "durable_memories": bundle.durable_memories,
        "past_experiences": bundle.past_experiences,
        "knowledge_refs": bundle.knowledge_refs,
        "flat_memories": bundle.flatten(),
        "counts": {
            "session_context": len(bundle.session_context),
            "durable_memories": len(bundle.durable_memories),
            "past_experiences": len(bundle.past_experiences),
            "knowledge_refs": len(bundle.knowledge_refs),
            "flat_memories": len(bundle.flatten()),
        },
        "prompt_preview": build_memory_prompt_sections(bundle),
    }


def _get_freshness_label(memory: MemoryNote) -> str:
    """给记忆打一个“新鲜度”标签，便于前端直接展示。"""
    return get_freshness_label(memory, now=datetime.now())
