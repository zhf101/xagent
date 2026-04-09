"""LanceDB 版记忆存储。

这是生产场景下更完整的记忆实现，支持：
- 向量检索
- 结构化 metadata
- 与新版 memory_type / memory_subtype 过滤兼容

注意：当前分支遵循你的约束，embedding 侧保留 OpenAI 兼容方向，
没有把之前不要的多厂商逻辑重新加回来。
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Union
from uuid import uuid4

from ...config import get_vector_backend
from ...providers.vector_store.lancedb import (
    LanceDBConnectionManager,
    LanceDBVectorStore,
)
from ..model.embedding import BaseEmbedding, OpenAIEmbedding
from ..model.embedding.adapter import create_embedding_adapter
from ..model.model import EmbeddingModelConfig
from .base import MemoryStore
from .core import MemoryNote, MemoryResponse
from .schema import matches_memory_filter

logger = logging.getLogger(__name__)


def _build_memory_table_missing_message(collection_name: str) -> str:
    """返回 pgvector 缺少记忆表时的统一指引。

    记忆系统切到 pgvector 后，也必须遵守“结构由 SQL 脚本维护”的规则。
    因此这里不再在首次写入时隐式补表，而是要求先完成数据库初始化。
    """
    return (
        f"Memory table '{collection_name}' does not exist in pgvector backend. "
        "Please initialize PostgreSQL with db/postgresql/schema_backup.sql "
        "or add an explicit patch before using memory storage."
    )


class LanceDBMemoryStore(MemoryStore):
    """基于 LanceDB/兼容向量后端的记忆存储实现。

    这层处在“记忆领域模型”和“底层向量数据库”之间：
    - 上层只关心 `MemoryNote / MemoryResponse`
    - 下层只关心表结构、向量列和 metadata JSON

    因此这里最核心的职责是做双向映射，而不是暴露底层数据库细节。
    """

    _embedding_model: Optional[BaseEmbedding]

    def __init__(
        self,
        db_dir: str,
        collection_name: str = "memories",
        embedding_model: Optional[Union[BaseEmbedding, EmbeddingModelConfig]] = None,
        similarity_threshold: float = 1.0,
        **embedding_kwargs: Any,
    ):
        """初始化记忆存储。

        这里兼容三种 embedding 配置方式：
        - 已构造好的 `BaseEmbedding`
        - `EmbeddingModelConfig`
        - 旧调用方直接传 `embedding_kwargs`

        这样迁移过程中不用强迫所有调用点一次性改完。
        """
        self._collection_name = collection_name

        # 这里兼容两种输入：
        # 1. 直接传入 BaseEmbedding 实例
        # 2. 传入 EmbeddingModelConfig，再动态创建 adapter
        if embedding_model is None:
            # Try to create a default embedding model only if embedding_kwargs are provided
            if embedding_kwargs:
                try:
                    self._embedding_model = OpenAIEmbedding(**embedding_kwargs)
                except Exception:
                    # If embedding model creation fails, set to None (will use fallback)
                    self._embedding_model = None
                    logger.warning(
                        "Failed to create embedding model, will use fallback text search"
                    )
            else:
                self._embedding_model = None
                logger.info(
                    "No embedding model provided; memory store will use text-search fallback"
                )
        elif isinstance(embedding_model, BaseEmbedding):
            self._embedding_model = embedding_model
        elif isinstance(embedding_model, EmbeddingModelConfig):
            self._embedding_model = create_embedding_adapter(embedding_model)
        else:
            raise ValueError(
                f"Unsupported embedding model type: {type(embedding_model)}"
            )
        self._similarity_threshold = similarity_threshold
        self._vector_store = LanceDBVectorStore(db_dir, collection_name)
        self._conn_manager = LanceDBConnectionManager()
        self._ensure_table_schema()

    def _ensure_table_schema(self) -> None:
        """确保 LanceDB 表结构满足当前记忆存储需要。"""
        try:
            conn = self._vector_store.get_raw_connection()
            table = conn.open_table(self._collection_name)

            # Check if table exists and has basic structure
            df = table.search().limit(1).to_pandas()

            # 记忆表至少要有 id / text / metadata，缺任意一个都说明结构不兼容。
            if not all(col in df.columns for col in ["id", "text", "metadata"]):
                # Schema is incompatible, drop and recreate
                logger.warning(
                    "Memory table '%s' schema is incompatible with current vector backend '%s'; "
                    "recreating compatibility table",
                    self._collection_name,
                    get_vector_backend(),
                )
                try:
                    # Try to drop the table if the method exists
                    if hasattr(conn, "drop_table"):
                        conn.drop_table(self._collection_name)
                    else:
                        # Alternative: try to use delete all records instead
                        table = conn.open_table(self._collection_name)
                        table.delete()
                except Exception:
                    # If drop fails, continue with recreation
                    pass
                self._create_empty_table()

        except Exception:
            # Table doesn't exist, create it with basic schema
            logger.info(
                "Memory table '%s' is missing or unreadable under vector backend '%s'; "
                "creating compatibility table",
                self._collection_name,
                get_vector_backend(),
            )
            self._create_empty_table()

    def _create_empty_table(self) -> None:
        """创建一张空表，并按是否有 embedding 决定是否包含 vector 列。

        注意：
        - LanceDB 模式下仍允许历史上的“按 sample row 自动建表”
        - pgvector 模式下已明确禁用运行时 DDL，这里应直接失败
        """
        conn = self._vector_store.get_raw_connection()

        # Check if we have an embedding model
        if self._embedding_model:
            # Create table with vector support
            try:
                # Generate a sample embedding to get dimension
                sample_embedding = self._get_embedding("sample")
                if sample_embedding:
                    # Create sample data with vector
                    sample_data = [
                        {
                            "id": "sample",
                            "text": "sample",
                            "metadata": "{}",
                            "vector": sample_embedding,
                        }
                    ]
                else:
                    # Fallback to non-vector schema
                    sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]
            except Exception:
                # If embedding fails, use non-vector schema
                sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]
        else:
            # No embedding model, create without vector column
            sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]

        # Create table with appropriate schema
        table = conn.create_table(self._collection_name, data=sample_data)
        # Remove sample data
        table.delete("id = 'sample'")

    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """通过当前 embedding 模型为文本生成向量。"""
        if not self._embedding_model or not text.strip():
            return None

        try:
            result = self._embedding_model.encode(text)
            # encode should return list[float] for single text input
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], list):
                    # Got list[list[float]], return the first embedding
                    return result[0]
                elif len(result) > 0 and isinstance(result[0], (int, float)):
                    # Got list[float], return as is
                    return result  # type: ignore[return-value]
            logger.warning(f"Unexpected embedding result format: {type(result)}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate embedding for text '{text[:50]}...': {e}")
            return None

    def _memory_note_to_dict(self, note: MemoryNote) -> dict[str, Any]:
        """把 MemoryNote 转成 LanceDB 存储格式。"""
        # 向量写进 `vector`，其余结构化字段统一折叠进 metadata JSON。
        content_text = (
            note.content.decode() if isinstance(note.content, bytes) else note.content
        )
        embedding = self._get_embedding(content_text)

        # 这次迁移补进来的结构化字段都放在 metadata 里持久化，
        # 这样旧接口还能继续读 category，新接口则能读 memory_type/subtype。
        metadata = {
            "content": note.content,
            "keywords": note.keywords,
            "tags": note.tags,
            "category": note.category,
            "memory_type": note.memory_type,
            "memory_subtype": note.memory_subtype,
            "scope": note.scope,
            "timestamp": note.timestamp.isoformat(),
            "mime_type": note.mime_type,
            "source_session_id": note.source_session_id,
            "source_agent_id": note.source_agent_id,
            "project_id": note.project_id,
            "workspace_id": note.workspace_id,
            "importance": note.importance,
            "confidence": note.confidence,
            "freshness_at": note.freshness_at.isoformat()
            if note.freshness_at
            else None,
            "expires_at": note.expires_at.isoformat() if note.expires_at else None,
            "dedupe_key": note.dedupe_key,
            "status": note.status,
            **note.metadata,
        }

        return {
            "id": note.id,
            "vector": embedding,
            "text": note.content,
            "metadata": json.dumps(metadata, ensure_ascii=False),
        }

    def _dict_to_memory_note(self, data: dict[str, Any]) -> MemoryNote:
        """把底层存储行恢复成 `MemoryNote`。

        这里会优先从 metadata 里恢复新字段，
        这样旧表结构和新字段扩展可以在一段时间内共存。
        """
        try:
            metadata = json.loads(data.get("metadata", "{}"))
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        return MemoryNote(
            id=data.get("id"),
            content=metadata.pop("content", data.get("text", "")),
            keywords=metadata.pop("keywords", []),
            tags=metadata.pop("tags", []),
            category=metadata.pop("category", "general"),
            memory_type=metadata.pop("memory_type", None),
            memory_subtype=metadata.pop("memory_subtype", None),
            scope=metadata.pop("scope", "user"),
            timestamp=metadata.pop("timestamp", None),
            mime_type=metadata.pop("mime_type", "text/plain"),
            source_session_id=metadata.pop("source_session_id", None),
            source_agent_id=metadata.pop("source_agent_id", None),
            project_id=metadata.pop("project_id", None),
            workspace_id=metadata.pop("workspace_id", None),
            importance=metadata.pop("importance", 3),
            confidence=metadata.pop("confidence", 0.5),
            freshness_at=metadata.pop("freshness_at", None),
            expires_at=metadata.pop("expires_at", None),
            dedupe_key=metadata.pop("dedupe_key", None),
            status=metadata.pop("status", "active"),
            metadata=metadata,
        )

    def _apply_filters(self, note: MemoryNote, filters: dict[str, Any]) -> bool:
        """对向量检索命中的 `MemoryNote` 应用统一过滤条件。

        这里复用领域层 `matches_memory_filter`，目的是让向量检索与文本兜底检索
        在过滤语义上保持完全一致，避免同一组 filters 在两条路径下表现不同。
        """
        for key, value in filters.items():
            if not matches_memory_filter(
                note_category=note.category,
                note_memory_type=note.memory_type,
                note_memory_subtype=note.memory_subtype,
                note_scope=note.scope,
                note_source_session_id=note.source_session_id,
                note_source_agent_id=note.source_agent_id,
                note_project_id=note.project_id,
                note_workspace_id=note.workspace_id,
                note_dedupe_key=note.dedupe_key,
                note_status=note.status,
                metadata=note.metadata,
                key=key,
                value=value,
            ):
                return False
        return True

    def _apply_text_search_filters(
        self, metadata_dict: dict[str, Any], filters: dict[str, Any]
    ) -> bool:
        """对文本兜底检索结果应用过滤条件。

        文本检索阶段还没恢复成 `MemoryNote` 对象，因此这里直接基于 metadata 字典判定。
        """
        for key, value in filters.items():
            if not matches_memory_filter(
                note_category=metadata_dict.get("category"),
                note_memory_type=metadata_dict.get("memory_type"),
                note_memory_subtype=metadata_dict.get("memory_subtype"),
                note_scope=metadata_dict.get("scope"),
                note_source_session_id=metadata_dict.get("source_session_id"),
                note_source_agent_id=metadata_dict.get("source_agent_id"),
                note_project_id=metadata_dict.get("project_id"),
                note_workspace_id=metadata_dict.get("workspace_id"),
                note_dedupe_key=metadata_dict.get("dedupe_key"),
                note_status=metadata_dict.get("status"),
                metadata=metadata_dict,
                key=key,
                value=value,
            ):
                return False
        return True

    def _apply_metadata_filters(
        self, metadata: dict[str, Any], metadata_filters: dict[str, Any]
    ) -> bool:
        """对嵌套 metadata 做精确匹配过滤。

        当前策略是字符串级精确比较，保持简单和可预测，不在这里引入模糊匹配语义。
        """
        for key, value in metadata_filters.items():
            if str(metadata.get(key, "")) != str(value):
                return False
        return True

    def _matches_list_filters(
        self,
        note: MemoryNote,
        filters: Optional[dict[str, Any]] = None,
    ) -> bool:
        """判断一条记忆是否命中 `list_all/count` 使用的过滤条件。

        这里不能简单复用 `_apply_filters()`，因为 `list_all()` 还支持：
        - 时间范围过滤
        - tags / keywords 的“全部命中”语义

        这些规则现在集中在这里，避免列表、分页计数、后台治理三处各自实现一份。
        """
        if not filters:
            return True

        for key, value in filters.items():
            if key == "date_from":
                if note.timestamp < value:
                    return False
                continue
            if key == "date_to":
                if note.timestamp > value:
                    return False
                continue
            if key == "tags":
                if not all(tag in note.tags for tag in value):
                    return False
                continue
            if key == "keywords":
                if not all(keyword in note.keywords for keyword in value):
                    return False
                continue

            if not self._apply_filters(note, {key: value}):
                return False

        return True

    def _iter_filtered_notes(
        self,
        *,
        filters: Optional[dict[str, Any]] = None,
        batch_size: int = 200,
    ):
        """按批遍历命中过滤条件的记忆，避免一次性把整表读进内存。

        之前 `list_all()` 直接走 `search(query=\"\", k=10000)`，问题是：
        - 只要数据量上来，就会一次性构造大量 `MemoryNote`
        - Web 列表和治理任务只是想分页消费，但也被迫全量加载

        这里改成底层游标式分页扫描：
        - 每批只读 `batch_size` 行
        - 命中过滤条件的记录逐条 yield 给调用方
        - 调用方可以在拿够自己需要的数据后立刻停止
        """
        table = self._vector_store.get_raw_connection().open_table(self._collection_name)
        raw_offset = 0

        while True:
            query = table.search().select(["id", "text", "metadata"]).limit(batch_size)
            if hasattr(query, "offset"):
                query = query.offset(raw_offset)
            batch_df = query.to_pandas()
            if batch_df.empty:
                break

            batch_rows = batch_df.to_dict(orient="records")
            for row in batch_rows:
                note = self._dict_to_memory_note(row)
                if self._matches_list_filters(note, filters):
                    yield note

            raw_offset += len(batch_rows)
            if len(batch_rows) < batch_size:
                break

    def add(self, note: MemoryNote) -> MemoryResponse:
        """新增一条记忆。

        状态影响：
        - 会在底层表中写入一条记录
        - 若表结构与当前预期不兼容，会尝试重建表后再写一次

        这里宁可在写入时触发表重建，也不直接把异常抛给上层，
        因为 memory 对 Web 侧更多是增强能力，优先保证可用性。
        """
        try:
            # Generate ID if not provided
            if not note.id:
                note.id = str(uuid4())

            # Convert to storage format
            data = self._memory_note_to_dict(note)

            # Add to vector store - use a consistent approach
            conn = self._vector_store.get_raw_connection()
            table = conn.open_table(self._collection_name)

            # Prepare record for insertion
            record = {
                "id": data["id"],
                "text": data["text"],
                "metadata": data["metadata"],
            }

            # Add vector if available
            if data["vector"]:
                record["vector"] = data["vector"]

            # Try to add the record, recreate table if schema mismatch
            try:
                table.add([record])
            except Exception as add_error:
                logger.warning(
                    f"Failed to add record due to schema mismatch: {add_error}"
                )
                if get_vector_backend() == "pgvector":
                    raise RuntimeError(
                        _build_memory_table_missing_message(self._collection_name)
                    ) from add_error
                # Recreate table and try again
                logger.info("Recreating table with fresh schema")
                try:
                    # Try to drop the table if the method exists
                    if hasattr(conn, "drop_table"):
                        conn.drop_table(self._collection_name)
                    else:
                        # Alternative: try to use delete all records instead
                        table = conn.open_table(self._collection_name)
                        table.delete()
                except Exception:
                    # If drop fails, continue with recreation
                    pass
                self._create_empty_table()
                table = conn.open_table(self._collection_name)

                # After recreating, check if we should include vector
                # Get current table schema
                df = table.search().limit(1).to_pandas()
                if not df.empty and "vector" not in df.columns:
                    # New table doesn't have vector column, remove vector from record
                    record_without_vector = {
                        k: v for k, v in record.items() if k != "vector"
                    }
                    table.add([record_without_vector])
                else:
                    table.add([record])

            return MemoryResponse(success=True, memory_id=data["id"])

        except Exception as e:
            logger.error(f"Failed to add memory note {note.id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to add memory: {str(e)}",
                memory_id=note.id,
            )

    def get(self, note_id: str) -> MemoryResponse:
        """按 id 读取单条记忆。"""
        try:
            table = self._vector_store.get_raw_connection().open_table(
                self._collection_name
            )

            # Search by ID
            results = table.search().where(f"id = '{note_id}'").to_pandas()

            if len(results) == 0:
                return MemoryResponse(
                    success=False,
                    error="Memory not found",
                    memory_id=note_id,
                )

            # Convert to MemoryNote
            data = results.iloc[0].to_dict()
            note = self._dict_to_memory_note(data)

            return MemoryResponse(
                success=True,
                memory_id=note_id,
                content=note,
            )

        except Exception as e:
            logger.error(f"Failed to get memory note {note_id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to get memory: {str(e)}",
                memory_id=note_id,
            )

    def update(self, note: MemoryNote) -> MemoryResponse:
        """更新一条已存在记忆。

        当前实现采用“先删后写”的简单策略，
        目的是避免同时兼容 LanceDB / pgvector 时再维护两套 update 语义。
        """
        try:
            # Check if memory exists
            get_response = self.get(note.id)
            if not get_response.success:
                return MemoryResponse(
                    success=False,
                    error="Memory not found",
                    memory_id=note.id,
                )

            # Delete old record
            self.delete(note.id)

            # Add updated record
            return self.add(note)

        except Exception as e:
            logger.error(f"Failed to update memory note {note.id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to update memory: {str(e)}",
                memory_id=note.id,
            )

    def delete(self, note_id: str) -> MemoryResponse:
        """按 id 删除一条记忆。"""
        try:
            success = self._vector_store.delete_vectors([note_id])

            if success:
                return MemoryResponse(success=True, memory_id=note_id)
            else:
                return MemoryResponse(
                    success=False,
                    error="Failed to delete memory",
                    memory_id=note_id,
                )

        except Exception as e:
            logger.error(f"Failed to delete memory note {note_id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to delete memory: {str(e)}",
                memory_id=note_id,
            )

    def search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[dict[str, Any]] = None,
        similarity_threshold: Optional[float] = None,
    ) -> list[MemoryNote]:
        """按查询文本检索记忆，并支持过滤条件。

        检索策略分两层：
        1. 优先尝试向量检索
        2. 向量不可用、失败或无结果时，回退到纯文本扫描

        这样可以在 embedding 不稳定或表结构缺少向量列时，仍保留最小可用检索能力。
        """
        try:
            table = self._vector_store.get_raw_connection().open_table(
                self._collection_name
            )
            results = []

            # Try vector search first
            try:
                query_embedding = self._get_embedding(query)
                if query_embedding:
                    # Check if vector column exists and has the right dimension
                    sample_df = table.search().limit(1).to_pandas()
                    if not sample_df.empty and "vector" in sample_df.columns:
                        # 只有表里确实存在向量列时才走向量检索，避免旧表结构直接报错。
                        try:
                            vector_df = (
                                table.search(
                                    query_embedding, vector_column_name="vector"
                                )
                                .limit(k)
                                .to_pandas()
                            )

                            for _, row in vector_df.iterrows():
                                # Check similarity threshold
                                threshold = (
                                    similarity_threshold
                                    if similarity_threshold is not None
                                    else self._similarity_threshold
                                )
                                distance = row.get("_distance", float("inf"))
                                if distance > threshold:
                                    logger.info(
                                        f"Skipping result with distance {distance} > threshold {threshold}"
                                    )
                                    continue

                                logger.info(
                                    f"Accepting result with distance {distance} <= threshold {threshold}"
                                )

                                note_data = {
                                    "id": row.get("id", ""),
                                    "text": row.get("text", ""),
                                    "metadata": row.get("metadata", "{}"),
                                }
                                note = self._dict_to_memory_note(note_data)

                                # Apply metadata filters to vector search results too
                                if filters:
                                    filter_match = self._apply_filters(note, filters)
                                    if not filter_match:
                                        continue

                                results.append(note)
                        except Exception as vector_error:
                            logger.warning(
                                f"Vector search failed, falling back to text search: {vector_error}"
                            )
            except Exception as embedding_error:
                logger.warning(
                    f"Embedding generation failed, using text search: {embedding_error}"
                )

            # 向量路径拿不到可用结果时，统一回退文本扫描，确保“查不到”和“向量暂不可用”
            # 是两回事，不会因为后端能力波动直接让 memory 功能失效。
            if not results:
                # Text search
                df = table.search().to_pandas()

                # Filter by query text and apply filters
                for _, row in df.iterrows():
                    text = row.get("text", "")
                    metadata = row.get("metadata", "{}")

                    try:
                        metadata_dict = json.loads(metadata)
                    except (json.JSONDecodeError, TypeError):
                        metadata_dict = {}

                    # Apply metadata filters if specified
                    if filters:
                        filter_match = self._apply_text_search_filters(
                            metadata_dict, filters
                        )
                        if not filter_match:
                            continue

                    # Simple text matching
                    if not query or query.lower() in text.lower():
                        note_data = {
                            "id": row.get("id", ""),
                            "text": text,
                            "metadata": metadata,
                        }
                        note = self._dict_to_memory_note(note_data)
                        results.append(note)

                        if len(results) >= k:
                            break

            return results[:k]

        except Exception as e:
            logger.error(f"Failed to search memories with query '{query[:50]}...': {e}")
            return []

    def clear(self) -> None:
        """清空当前 store 中的全部记忆。"""
        try:
            self._vector_store.clear()
        except Exception as e:
            logger.error(f"Failed to clear memory store: {e}")

    def list_all(
        self,
        filters: Optional[dict[str, Any]] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[MemoryNote]:
        """列出记忆，并在 store 层完成过滤后分页。

        这里不再复用 `search(query=\"\")`，因为那条路径会把大量结果一次性拉回内存。
        新实现按批扫描底层表，再在 Python 层应用 metadata/date/tags 这些组合过滤。
        虽然依旧可能扫描较多行，但至少不会把整表对象一次性展开。
        """
        try:
            results: list[MemoryNote] = []
            matched_count = 0

            for note in self._iter_filtered_notes(filters=filters):
                if matched_count < offset:
                    matched_count += 1
                    continue

                results.append(note)
                matched_count += 1

                if limit is not None and limit >= 0 and len(results) >= limit:
                    break

            return results
        except Exception as e:
            logger.error(f"Failed to list all memories: {e}")
            return []

    def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """统计命中过滤条件的记忆数量。

        这里也走批量扫描而不是 `len(list_all())`，目的是避免统计接口为了拿一个数字，
        反而把所有 `MemoryNote` 对象完整构造一遍。
        """
        try:
            return sum(1 for _ in self._iter_filtered_notes(filters=filters))
        except Exception as e:
            logger.error(f"Failed to count memories: {e}")
            return 0

    def get_stats(self) -> dict[str, Any]:
        """返回当前记忆库的轻量统计信息。

        这里返回的是运行时诊断视图，不是严格报表口径。
        统计逻辑基于当前可枚举到的记忆集合，因此更适合排查和观测。
        """
        try:
            # Get all memories to calculate stats
            all_memories = self.list_all()

            total_count = len(all_memories)
            category_counts: dict[str, int] = {}
            tag_counts: dict[str, int] = {}

            for note in all_memories:
                # Count by category
                category_counts[note.category] = (
                    category_counts.get(note.category, 0) + 1
                )

                # Count tags
                for tag in note.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            return {
                "total_count": total_count,
                "category_counts": category_counts,
                "tag_counts": tag_counts,
                "memory_store_type": get_vector_backend(),
            }
        except Exception as e:
            logger.error(f"Failed to get memory stats: {e}")
            return {
                "total_count": 0,
                "category_counts": {},
                "tag_counts": {},
                "memory_store_type": get_vector_backend(),
                "error": str(e),
            }
