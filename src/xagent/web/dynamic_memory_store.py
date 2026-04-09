"""Web 层动态 memory store 管理器。

这个模块解决的是“记忆存储后端会随配置变化而切换”这个问题。

当前系统支持两类主要后端：
- `InMemoryMemoryStore`：无 embedding model 时的最小可用兜底
- `LanceDBMemoryStore` / 兼容向量后端：有 embedding model 时提供向量检索

如果在启动时就把 store 固定死，会出现两个问题：
- 用户后来补了 embedding model，但服务还停留在 in-memory
- 模型配置切换后，记忆检索仍然使用旧的向量参数

因此这里引入一个全局 manager，在每次获取 store 时做一次轻量检查，
按当前配置动态决定是否重建底层存储。
"""

import logging
import os
import threading
from typing import Optional, Union

from ..config import get_vector_backend
from ..core.memory.in_memory import InMemoryMemoryStore
from ..core.memory.lancedb import LanceDBMemoryStore
from ..core.model.embedding import OpenAIEmbedding
from ..core.storage.manager import get_storage_root
from .models.database import get_db
from .models.model import Model as DBModel
from .models.user import UserDefaultModel
from .user_isolated_memory import UserIsolatedMemoryStore, current_user_id

logger = logging.getLogger(__name__)

# Type alias for our memory store types that includes user isolation
MemoryStoreType = Union[
    InMemoryMemoryStore, LanceDBMemoryStore, UserIsolatedMemoryStore
]


class DynamicMemoryStoreManager:
    """动态 memory store 管理器。

    这个类的职责不是实现记忆检索本身，而是维护“当前 Web 进程应该使用哪一种 store”。
    它要同时满足：
    - 延迟初始化，避免启动时强依赖 embedding model
    - 可重配置，模型切换后能够自动切换后端
    - 线程安全，避免并发请求下重复初始化或半初始化状态泄漏
    """

    def __init__(self, similarity_threshold: Optional[float] = None):
        """初始化管理器。"""
        self._similarity_threshold = similarity_threshold
        self._memory_store: Optional[MemoryStoreType] = None
        self._lock = threading.RLock()
        self._last_embedding_model_id: Optional[int] = None
        self._is_lancedb: bool = False

        self._check_and_update_store()

    def _initialize_in_memory_store(self) -> None:
        """初始化为内存型 store。

        这是所有失败场景和未配置场景的统一安全回退点。
        """
        with self._lock:
            in_memory_store = InMemoryMemoryStore()
            self._memory_store = UserIsolatedMemoryStore(in_memory_store)
            self._is_lancedb = False
            self._last_embedding_model_id = None
            logger.info("Initialized with in-memory store")

    def _get_embedding_model_from_db(self) -> Optional[DBModel]:
        """从数据库读取当前生效的 embedding model。

        优先级规则：
        1. 若当前请求上下文带有 user_id，优先读该用户自己的默认 embedding model
        2. 否则回退到系统里任意一个可用的 embedding model

        这样能兼顾多租户隔离和“系统至少能跑起来”的可用性。
        """
        try:
            db = next(get_db())
            try:
                # Get current user ID from context
                user_id = current_user_id.get()

                if user_id:
                    # First, try to get user's default embedding model
                    user_default = (
                        db.query(UserDefaultModel)
                        .filter(
                            UserDefaultModel.user_id == user_id,
                            UserDefaultModel.config_type == "embedding",
                        )
                        .first()
                    )

                    if user_default:
                        # Get the actual model
                        embedding_model = (
                            db.query(DBModel)
                            .filter(
                                DBModel.id == user_default.model_id,
                                DBModel.category == "embedding",
                                DBModel.is_active,
                            )
                            .first()
                        )
                        if embedding_model:
                            logger.info(
                                f"Found user's default embedding model: {embedding_model.model_id}"
                            )
                            return embedding_model
                        else:
                            logger.warning(
                                f"User default embedding model {user_default.model_id} not found or inactive"
                            )

                # Fallback: look for any active embedding model
                embedding_model = (
                    db.query(DBModel)
                    .filter(
                        DBModel.category == "embedding",
                        DBModel.is_active,
                    )
                    .first()
                )

                if embedding_model:
                    logger.info(
                        f"Using system active embedding model (user has no default): {embedding_model.model_id}"
                    )
                else:
                    logger.info("No active embedding model found")

                return embedding_model
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error checking for embedding model: {e}")
            return None

    def _create_lancedb_store(
        self, embedding_model: Optional[DBModel]
    ) -> UserIsolatedMemoryStore:
        """基于 embedding model 创建向量型 memory store。

        这里仍保留对历史 `memory_store/` 目录的兼容，
        避免老环境升级后直接丢失已有本地数据。
        """
        try:
            # Check legacy location (project root) first for backward compatibility
            legacy_dir = os.path.join(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                ),
                "memory_store",
            )
            if os.path.exists(legacy_dir) and os.listdir(legacy_dir):
                logger.info(
                    "Detected legacy memory_store directory for compatibility: %s "
                    "(when backend=pgvector, vectors still persist in PostgreSQL)",
                    legacy_dir,
                )
                db_dir = legacy_dir
            else:
                # Use new default location
                new_dir = get_storage_root() / "memory_store"
                os.makedirs(new_dir, exist_ok=True)
                db_dir = str(new_dir)

            if embedding_model is None:
                lancedb_store = LanceDBMemoryStore(
                    db_dir=db_dir,
                    embedding_model=None,
                    similarity_threshold=self._similarity_threshold or 1.5,
                )
                logger.info(
                    "Created %s-backed memory store without embedding model (text search fallback)",
                    get_vector_backend(),
                )
                return UserIsolatedMemoryStore(lancedb_store)
            elif embedding_model.model_provider == "openai":
                lancedb_store = LanceDBMemoryStore(
                    db_dir=db_dir,
                    embedding_model=OpenAIEmbedding(
                        model=str(embedding_model.model_name),
                        api_key=str(embedding_model.api_key),
                        base_url=str(embedding_model.base_url)
                        if embedding_model.base_url
                        else None,
                        dimension=int(embedding_model.dimension or 1024),
                    ),
                    similarity_threshold=self._similarity_threshold or 1.5,
                )
                logger.info(
                    "Created %s-backed memory store with OpenAI-compatible embedding model",
                    get_vector_backend(),
                )
                return UserIsolatedMemoryStore(lancedb_store)
            else:
                # 当前只对 OpenAI-compatible embedding 走通向量 store。
                logger.warning(
                    f"Unsupported embedding model type: {embedding_model.model_provider}"
                )
                if get_vector_backend() == "pgvector":
                    lancedb_store = LanceDBMemoryStore(
                        db_dir=db_dir,
                        embedding_model=None,
                        similarity_threshold=self._similarity_threshold or 1.5,
                    )
                    return UserIsolatedMemoryStore(lancedb_store)
                self._initialize_in_memory_store()
                return self._memory_store  # type: ignore[return-value]
        except Exception as e:
            logger.error("Error creating persistent vector memory store: %s", e)
            # 任意向量 store 构造失败都统一回退到 in-memory，确保 Web 侧记忆能力不至于整体不可用。
            self._initialize_in_memory_store()
            return self._memory_store  # type: ignore[return-value]

    def _check_and_update_store(self) -> None:
        """检查配置并更新 store 实例。

        如果是首次初始化且后端指定了 pgvector，则直接挂载持久化存储。
        """
        embedding_model = self._get_embedding_model_from_db()
        current_model_id = embedding_model.id if embedding_model else None
        is_pgvector = get_vector_backend() == "pgvector"

        with self._lock:
            if not self._memory_store:
                if embedding_model or is_pgvector:
                    self._memory_store = self._create_lancedb_store(embedding_model)
                    self._is_lancedb = True
                    self._last_embedding_model_id = current_model_id
                    logger.info(
                        "Initialized persistent vector memory store directly (backend=%s)",
                        "pgvector" if is_pgvector else "lancedb",
                    )
                else:
                    self._initialize_in_memory_store()
                return

            if (embedding_model or is_pgvector) and not self._is_lancedb:
                self._memory_store = self._create_lancedb_store(embedding_model)
                self._is_lancedb = True
                self._last_embedding_model_id = current_model_id
                logger.info(
                    "Switched to persistent vector memory store (backend=%s)",
                    "pgvector" if is_pgvector else "lancedb",
                )
            elif (
                (embedding_model or is_pgvector)
                and self._is_lancedb
                and current_model_id != self._last_embedding_model_id
            ):
                self._memory_store = self._create_lancedb_store(embedding_model)
                self._last_embedding_model_id = current_model_id
                logger.info(
                    "Embedding model changed; rebuilding persistent vector memory store "
                    "(backend=%s)",
                    "pgvector" if is_pgvector else "lancedb",
                )
            elif not embedding_model and not is_pgvector and self._is_lancedb:
                self._initialize_in_memory_store()
                logger.info("No embedding model and not pgvector, falling back to in-memory")

    def get_memory_store(self) -> MemoryStoreType:
        """返回当前应生效的 memory store。

        每次取值前都会先做一次配置检查，确保调用方拿到的是“现在正确”的 store，
        而不是某次启动时遗留下来的旧实例。
        """
        self._check_and_update_store()
        return self._memory_store  # type: ignore[return-value]

    def force_reinitialize(self) -> None:
        """强制重建 memory store。"""
        with self._lock:
            self._initialize_in_memory_store()
            self._check_and_update_store()
            logger.info("Force reinitialized memory store")

    def check_embedding_model_change(self) -> bool:
        """检查 embedding model 变化，并返回这次是否真的触发了 store 切换。"""
        with self._lock:
            old_is_lancedb = self._is_lancedb
            old_model_id = self._last_embedding_model_id

            self._check_and_update_store()

            # Return true if anything changed
            return (
                old_is_lancedb != self._is_lancedb
                or old_model_id != self._last_embedding_model_id
            )

    def get_store_info(self) -> dict:
        """返回当前 store 的诊断信息。

        这个接口主要给启动日志、健康排查和管理页使用，
        目的是快速回答“现在到底跑的是哪种 memory backend”。
        """
        self._check_and_update_store()
        with self._lock:
            base_store = (
                self._memory_store._base_store
                if isinstance(self._memory_store, UserIsolatedMemoryStore)
                else self._memory_store
            )

            return {
                "store_type": type(base_store).__name__,
                "is_lancedb": self._is_lancedb,
                "vector_backend": get_vector_backend() if self._is_lancedb else None,
                "embedding_model_id": self._last_embedding_model_id,
                "similarity_threshold": self._similarity_threshold,
                "supports_vector_search": self._is_lancedb,
            }


# Global instance
_dynamic_manager: Optional[DynamicMemoryStoreManager] = None
_manager_lock = threading.Lock()


def get_memory_store_manager(
    similarity_threshold: Optional[float] = None,
) -> DynamicMemoryStoreManager:
    """获取全局单例 manager。

    这里故意把 manager 做成进程级单例，避免每次请求都重新探测 embedding model
    并重建底层 store，造成无谓的锁竞争和资源浪费。
    """
    global _dynamic_manager

    if _dynamic_manager is None:
        with _manager_lock:
            if _dynamic_manager is None:
                _dynamic_manager = DynamicMemoryStoreManager(similarity_threshold)

    return _dynamic_manager


def get_memory_store() -> MemoryStoreType:
    """获取当前 memory store。

    这个函数保留为兼容旧调用方的稳定入口。
    新代码如果需要更多诊断或强制刷新能力，应直接拿 manager。
    """
    manager = get_memory_store_manager()
    return manager.get_memory_store()


def force_reinitialize_memory_store() -> None:
    """强制重建当前全局 memory store。

    适用于管理操作或模型配置刚变更、需要立刻生效的场景。
    """
    manager = get_memory_store_manager()
    manager.force_reinitialize()
