"""知识库(KB)统一存储工厂 - Phase 1A存储解耦核心组件

【合并来源】main分支提交 98e68b3 - feat(kb): complete phase 1A storage decoupling

【设计思想】
在合并前的旧架构中,所有KB相关数据(向量索引、元数据、摄入状态等)都直接耦合在
LanceDB的单表中,导致:
1. 数据模型混乱 - 不同类型数据混在同一张表
2. 扩展困难 - 新增存储类型需要修改大量代码
3. 测试复杂 - 无法单独测试某个存储层
4. 性能瓶颈 - 所有操作都依赖LanceDB,无法替换为其他存储引擎

Phase 1A存储解耦的核心目标是:
- 将KB的6种存储职责完全分离(向量索引、元数据、摄入状态、提示词模板、主指针、写入协调)
- 定义清晰的抽象接口(Contracts),允许未来替换存储后端(如从LanceDB切换到PostgreSQL)
- 提供统一的工厂类管理所有存储实例的单例,保证全局一致性
- 保持向后兼容 - 旧代码仍可通过便捷函数访问

【架构分层】
┌─────────────────────────────────────────────┐
│         KB API Layer (kb.py)                │  ← REST API入口
├─────────────────────────────────────────────┤
│    Service Layer (kb_collection_service)    │  ← 业务逻辑层
├─────────────────────────────────────────────┤
│      StorageFactory (本文件)                 │  ← 单例工厂,统一获取存储实例
├─────────────────────────────────────────────┤
│    Contracts Interface (contracts.py)       │  ← 抽象接口定义
├─────────────────────────────────────────────┤
│  LanceDB Implementation (lancedb_stores.py) │  ← 具体实现
└─────────────────────────────────────────────┘

【6大存储契约说明】
1. VectorIndexStore  - 向量索引存储(文档chunk的embedding)
2. MetadataStore     - 元数据存储(collection配置、用户权限)
3. IngestionStatusStore - 摄入状态跟踪(文档处理进度)
4. PromptTemplateStore  - 提示词模板存储
5. MainPointerStore   - 主指针存储(用于蓝绿部署/版本切换)
6. KBWriteCoordinator - 写入协调器(保证多存储间的事务一致性)

【合并后改动】
- 新增StorageFactory单例模式,使用双重检查锁保证线程安全
- 所有存储实例延迟初始化,避免启动时创建不必要的连接
- 提供便捷函数(get_vector_index_store等)保持向后兼容
- 旧代码无需修改,新代码推荐使用StorageFactory
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from .contracts import (
    IngestionStatusStore,
    KBWriteCoordinator,
    MainPointerStore,
    MetadataStore,
    PromptTemplateStore,
    VectorIndexStore,
)
from .lancedb_stores import (
    LanceDBIngestionStatusStore,
    LanceDBMainPointerStore,
    LanceDBMetadataStore,
    LanceDBPromptTemplateStore,
    LanceDBVectorIndexStore,
)
from .vector_backend import (
    VectorBackend,
    get_configured_vector_backend,
    require_implemented_vector_backend,
)


class StorageFactory:
    """Unified factory for all storage contracts.

    Manages singleton instances of all stores with lazy initialization
    and thread-safe access using double-checked locking.

    Usage:
        factory = StorageFactory.get_factory()
        vector_store = factory.get_vector_index_store()
        metadata_store = factory.get_metadata_store()
    """

    _instance: Optional[StorageFactory] = None
    _lock = threading.RLock()  # RLock for reentrant locking

    def __init__(self) -> None:
        """Private constructor - use get_factory() instead."""
        if StorageFactory._instance is not None:
            raise RuntimeError("Use get_factory() to get StorageFactory instance")

        # Store instances (lazy initialization)
        self._vector_index_store: Optional[VectorIndexStore] = None
        self._vector_backend: Optional[VectorBackend] = None
        self._metadata_store: Optional[MetadataStore] = None
        self._ingestion_status_store: Optional[IngestionStatusStore] = None
        self._prompt_template_store: Optional[PromptTemplateStore] = None
        self._main_pointer_store: Optional[MainPointerStore] = None
        self._coordinator: Optional[KBWriteCoordinator] = None

    @classmethod
    def get_factory(cls) -> StorageFactory:
        """Get singleton factory instance.

        Uses double-checked locking for thread-safe lazy initialization.

        Returns:
            The singleton StorageFactory instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def reset_all(self) -> None:
        """Reset all store instances.

        Useful for tests/fixtures that need isolated storage.
        Thread-safe: uses factory lock to prevent race conditions.
        """
        with self._lock:
            self._vector_index_store = None
            self._vector_backend = None
            self._metadata_store = None
            self._ingestion_status_store = None
            self._prompt_template_store = None
            self._main_pointer_store = None
            self._coordinator = None

    # --- VectorIndexStore ---

    def get_vector_index_store(self) -> VectorIndexStore:
        """Get or create vector index store.

        Backend is selected via :envvar:`XAGENT_VECTOR_BACKEND` (or legacy
        ``VECTOR_STORE_BACKEND``); see :mod:`.vector_backend`.

        Returns:
            Concrete :class:`~.contracts.VectorIndexStore` (currently
            :class:`~.lancedb_stores.LanceDBVectorIndexStore` when backend is
            ``lancedb``).

        Raises:
            ConfigurationError: Unknown backend name, or backend not implemented
                yet (e.g. ``milvus`` / ``qdrant`` without an adapter).
        """
        if self._vector_index_store is None:
            with self._lock:
                if self._vector_index_store is None:
                    backend = get_configured_vector_backend()
                    require_implemented_vector_backend(backend)
                    if backend is VectorBackend.LANCEDB:
                        self._vector_index_store = LanceDBVectorIndexStore()
                        self._vector_backend = backend
                    else:
                        raise AssertionError(
                            "require_implemented_vector_backend must prevent this branch"
                        )
        return self._vector_index_store

    def get_resolved_vector_backend(self) -> VectorBackend:
        """Return the backend bound to the current vector index store singleton.

        After the store is created, this reflects the backend used at creation
        time (cached). Before creation, returns :func:`.get_configured_vector_backend`
        without instantiating the store.
        """
        if self._vector_backend is not None:
            return self._vector_backend
        return get_configured_vector_backend()

    # --- MetadataStore ---

    def get_metadata_store(self) -> MetadataStore:
        """Get or create metadata store.

        Returns:
            LanceDBMetadataStore instance.
        """
        if self._metadata_store is None:
            with self._lock:
                if self._metadata_store is None:
                    self._metadata_store = LanceDBMetadataStore()
        return self._metadata_store

    # --- IngestionStatusStore ---

    def get_ingestion_status_store(self) -> IngestionStatusStore:
        """Get or create ingestion status store.

        Returns:
            LanceDBIngestionStatusStore instance.
        """
        if self._ingestion_status_store is None:
            with self._lock:
                if self._ingestion_status_store is None:
                    self._ingestion_status_store = LanceDBIngestionStatusStore()
        return self._ingestion_status_store

    # --- PromptTemplateStore ---

    def get_prompt_template_store(self) -> PromptTemplateStore:
        """Get or create prompt template store.

        Returns:
            LanceDBPromptTemplateStore instance.
        """
        if self._prompt_template_store is None:
            with self._lock:
                if self._prompt_template_store is None:
                    self._prompt_template_store = LanceDBPromptTemplateStore()
        return self._prompt_template_store

    # --- MainPointerStore ---

    def get_main_pointer_store(self) -> MainPointerStore:
        """Get or create main pointer store.

        Returns:
            LanceDBMainPointerStore instance.
        """
        if self._main_pointer_store is None:
            with self._lock:
                if self._main_pointer_store is None:
                    self._main_pointer_store = LanceDBMainPointerStore()
        return self._main_pointer_store

    # --- KBWriteCoordinator ---

    def get_kb_write_coordinator(self) -> KBWriteCoordinator:
        """Get or create KB write coordinator.

        Returns:
            DefaultKBWriteCoordinator: Phase 1A shell delegating to metadata
            and vector stores only; see that class for future coordination scope.
        """
        if self._coordinator is None:
            with self._lock:
                if self._coordinator is None:
                    self._coordinator = DefaultKBWriteCoordinator(
                        metadata=self.get_metadata_store(),
                        vector_index=self.get_vector_index_store(),
                    )
        return self._coordinator


# ============================================================================
# Backward Compatibility Functions
# ============================================================================

# Module-level lock for backward compatibility functions
_compat_lock = threading.Lock()
_default_factory: Optional[StorageFactory] = None


def _get_default_factory() -> StorageFactory:
    """Get or create default factory instance (thread-safe)."""
    global _default_factory
    if _default_factory is None:
        with _compat_lock:
            if _default_factory is None:
                _default_factory = StorageFactory.get_factory()
    return _default_factory


def reset_kb_write_coordinator() -> None:
    """Reset process-global coordinator (useful for tests/fixtures).

    Deprecated: Use StorageFactory.get_factory().reset_all() instead.
    """
    _get_default_factory().reset_all()


def get_kb_write_coordinator() -> KBWriteCoordinator:
    """Return process-global KB write coordinator.

    Deprecated: Use StorageFactory.get_factory().get_kb_write_coordinator() instead.
    """
    return _get_default_factory().get_kb_write_coordinator()


def get_metadata_store() -> MetadataStore:
    """Convenience accessor for metadata store.

    Deprecated: Use StorageFactory.get_factory().get_metadata_store() instead.
    """
    return _get_default_factory().get_metadata_store()


def get_vector_index_store() -> VectorIndexStore:
    """Convenience accessor for vector index store.

    Deprecated: Use StorageFactory.get_factory().get_vector_index_store() instead.
    """
    return _get_default_factory().get_vector_index_store()


def get_vector_store_raw_connection() -> Any:
    """Return the LanceDB handle exposed by the vector index store singleton.

    Central entry point for RAG code that still needs a raw connection during
    Phase 1A. Replaces duplicated per-module ``get_connection_from_env`` helpers
    that only delegated to ``get_vector_index_store().get_raw_connection()``.

    Returns:
        The object returned by :meth:`VectorIndexStore.get_raw_connection`.
    """
    return get_vector_index_store().get_raw_connection()


def get_ingestion_status_store() -> IngestionStatusStore:
    """Get ingestion status store.

    Returns:
        LanceDBIngestionStatusStore instance.
    """
    return _get_default_factory().get_ingestion_status_store()


def get_prompt_template_store() -> PromptTemplateStore:
    """Get prompt template store.

    Returns:
        LanceDBPromptTemplateStore instance.
    """
    return _get_default_factory().get_prompt_template_store()


def get_main_pointer_store() -> MainPointerStore:
    """Get main pointer store.

    Returns:
        LanceDBMainPointerStore instance.
    """
    return _get_default_factory().get_main_pointer_store()


# ============================================================================
# Default Coordinator Implementation
# ============================================================================


class DefaultKBWriteCoordinator(KBWriteCoordinator):
    """In-process KB write coordinator: Phase 1A placeholder implementation.

    Only :meth:`metadata_store` and :meth:`vector_index_store` are implemented;
    both delegate to the injected or default LanceDB-backed stores. This is
    sufficient as a shell while call sites converge on :class:`KBWriteCoordinator`.
    Future phases may add distributed locking, batched writes, and conflict
    resolution without changing the high-level factory entry point.
    """

    def __init__(
        self,
        metadata: MetadataStore | None = None,
        vector_index: VectorIndexStore | None = None,
    ) -> None:
        self._metadata = metadata or LanceDBMetadataStore()
        self._vector_index = vector_index or LanceDBVectorIndexStore()

    def metadata_store(self) -> MetadataStore:
        return self._metadata

    def vector_index_store(self) -> VectorIndexStore:
        return self._vector_index
