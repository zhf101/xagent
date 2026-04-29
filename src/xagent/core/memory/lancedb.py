from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Union
from uuid import uuid4

from ...providers.vector_store.lancedb import (
    LanceDBConnectionManager,
    LanceDBVectorStore,
)
from ..model.embedding import BaseEmbedding, OpenAIEmbedding
from ..model.embedding.adapter import create_embedding_adapter
from ..model.model import EmbeddingModelConfig
from ..tools.core.RAG_tools.LanceDB.schema_manager import _safe_close_table
from .base import MemoryStore
from .core import MemoryNote, MemoryResponse

logger = logging.getLogger(__name__)


class LanceDBMemoryStore(MemoryStore):
    """基于 LanceDB 的记忆存储实现，支持向量检索。"""

    _embedding_model: Optional[BaseEmbedding]

    def __init__(
        self,
        db_dir: str,
        collection_name: str = "memories",
        embedding_model: Optional[Union[BaseEmbedding, EmbeddingModelConfig]] = None,
        similarity_threshold: float = 1.0,
        **embedding_kwargs: Any,
    ):
        """
        初始化 LanceDB 记忆存储。

        参数:
            db_dir: 数据库目录路径
            collection_name: 用于存储记忆的集合名称
            embedding_model: 可选的 BaseEmbedding 实例或 EmbeddingModel 配置
            similarity_threshold: 向量搜索的余弦距离阈值（值越小越严格）
            **embedding_kwargs: 传递给嵌入模型的额外参数
        """
        self._collection_name = collection_name

        # 处理不同类型的 embedding_model 输入
        if embedding_model is None:
            # 只在提供了 embedding_kwargs 时才尝试创建默认嵌入模型
            if embedding_kwargs:
                try:
                    self._embedding_model = OpenAIEmbedding(**embedding_kwargs)
                except Exception:
                    # 嵌入模型创建失败时，置为 None（将使用回退方案）
                    self._embedding_model = None
                    logger.warning(
                        "Failed to create embedding model, will use fallback text search"
                    )
            else:
                self._embedding_model = None
                logger.info(
                    "No embedding model provided, will use fallback text search"
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
        """确保表具有记忆存储所需的正确 schema。"""
        table = None
        try:
            conn = self._vector_store.get_raw_connection()
            table = conn.open_table(self._collection_name)

            # 检查表是否存在以及是否具有基本结构
            df = table.search().limit(1).to_pandas()

            # 表已存在，检查是否具有所需列
            if not all(col in df.columns for col in ["id", "text", "metadata"]):
                # schema 不兼容，删除后重建
                logger.warning(
                    f"Table {self._collection_name} has incompatible schema, recreating"
                )
                inner_table = None
                try:
                    # 尝试删除表（如果方法存在）
                    if hasattr(conn, "drop_table"):
                        conn.drop_table(self._collection_name)
                    else:
                        # 替代方案：尝试删除所有记录
                        inner_table = conn.open_table(self._collection_name)
                        inner_table.delete()
                except Exception:
                    # 删除失败则继续重建流程
                    pass
                finally:
                    _safe_close_table(inner_table)
                self._create_empty_table()

        except Exception:
            # 表不存在，使用基本 schema 创建
            logger.info(f"Creating table {self._collection_name} with basic schema")
            self._create_empty_table()
        finally:
            _safe_close_table(table)

    def _create_empty_table(self) -> None:
        """使用正确的 schema 创建一张空表。"""
        conn = self._vector_store.get_raw_connection()

        # 检查是否配置了嵌入模型
        if self._embedding_model:
            # 创建支持向量的表
            try:
                # 生成一条示例嵌入以获取维度
                sample_embedding = self._get_embedding("sample")
                if sample_embedding:
                    # 创建包含向量的示例数据
                    sample_data = [
                        {
                            "id": "sample",
                            "text": "sample",
                            "metadata": "{}",
                            "vector": sample_embedding,
                        }
                    ]
                else:
                    # 回退到无向量 schema
                    sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]
            except Exception:
                # 嵌入失败时使用无向量 schema
                sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]
        else:
            # 没有嵌入模型，创建时不包含向量列
            sample_data = [{"id": "sample", "text": "sample", "metadata": "{}"}]

        # 使用合适的 schema 创建表
        table = conn.create_table(self._collection_name, data=sample_data)
        # 删除示例数据
        table.delete("id = 'sample'")

    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """使用配置的嵌入模型获取文本的嵌入向量。"""
        if not self._embedding_model or not text.strip():
            return None

        try:
            result = self._embedding_model.encode(text)
            # encode 对单个文本输入应返回 list[float]
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], list):
                    # 得到 list[list[float]]，返回第一个嵌入
                    return result[0]
                elif len(result) > 0 and isinstance(result[0], (int, float)):
                    # 得到 list[float]，直接返回
                    return result  # type: ignore[return-value]
            logger.warning(f"Unexpected embedding result format: {type(result)}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate embedding for text '{text[:50]}...': {e}")
            return None

    def _memory_note_to_dict(self, note: MemoryNote) -> dict[str, Any]:
        """将 MemoryNote 转换为用于存储的字典。"""
        # 获取内容的嵌入向量
        content_text = (
            note.content.decode() if isinstance(note.content, bytes) else note.content
        )
        embedding = self._get_embedding(content_text)

        # 准备元数据
        metadata = {
            "content": note.content,
            "keywords": note.keywords,
            "tags": note.tags,
            "category": note.category,
            "timestamp": note.timestamp.isoformat(),
            "mime_type": note.mime_type,
            **note.metadata,
        }

        return {
            "id": note.id,
            "vector": embedding,
            "text": note.content,
            "metadata": json.dumps(metadata, ensure_ascii=False),
        }

    def _dict_to_memory_note(self, data: dict[str, Any]) -> MemoryNote:
        """将存储中的字典转换回 MemoryNote。"""
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
            timestamp=metadata.pop("timestamp", None),
            mime_type=metadata.pop("mime_type", "text/plain"),
            metadata=metadata,
        )

    def _apply_filters(self, note: MemoryNote, filters: dict[str, Any]) -> bool:
        """对向量搜索结果中的 MemoryNote 应用过滤条件。"""
        for key, value in filters.items():
            # 对 category 做特殊处理——先检查 note.category
            if key == "category":
                if str(note.category) != str(value):
                    return False
            elif key == "metadata":
                # 处理嵌套的元数据过滤
                if not self._apply_metadata_filters(note.metadata, value):
                    return False
            else:
                # 对于其他字段，检查元数据
                if str(note.metadata.get(key, "")) != str(value):
                    return False
        return True

    def _apply_text_search_filters(
        self, metadata_dict: dict[str, Any], filters: dict[str, Any]
    ) -> bool:
        """对文本搜索结果的元数据字典应用过滤条件。"""
        for key, value in filters.items():
            if key == "metadata":
                # 处理嵌套的元数据过滤
                if not self._apply_metadata_filters(metadata_dict, value):
                    return False
            else:
                # 直接字段比较
                if str(metadata_dict.get(key, "")) != str(value):
                    return False
        return True

    def _apply_metadata_filters(
        self, metadata: dict[str, Any], metadata_filters: dict[str, Any]
    ) -> bool:
        """应用嵌套的元数据过滤条件。"""
        for key, value in metadata_filters.items():
            if str(metadata.get(key, "")) != str(value):
                return False
        return True

    def add(self, note: MemoryNote) -> MemoryResponse:
        """将一条记忆添加到存储中。"""
        try:
            # 如果没有提供 ID，则生成一个
            if not note.id:
                note.id = str(uuid4())

            # 转换为存储格式
            data = self._memory_note_to_dict(note)

            # 添加到向量存储——使用一致的方法
            conn = self._vector_store.get_raw_connection()
            table = None
            try:
                table = conn.open_table(self._collection_name)

                # 准备要插入的记录
                record = {
                    "id": data["id"],
                    "text": data["text"],
                    "metadata": data["metadata"],
                }

                # 如果有向量则添加
                if data["vector"]:
                    record["vector"] = data["vector"]

                # 尝试添加记录，如果 schema 不匹配则重建表
                try:
                    table.add([record])
                except Exception as add_error:
                    logger.warning(
                        f"Failed to add record due to schema mismatch: {add_error}"
                    )
                    # 重建表并再次尝试
                    logger.info("Recreating table with fresh schema")
                    inner_table = None
                    try:
                        # 尝试删除表（如果方法存在）
                        if hasattr(conn, "drop_table"):
                            conn.drop_table(self._collection_name)
                        else:
                            # 替代方案：尝试删除所有记录
                            inner_table = conn.open_table(self._collection_name)
                            inner_table.delete()
                    except Exception:
                        # 删除失败则继续重建流程
                        pass
                    finally:
                        _safe_close_table(inner_table)
                    self._create_empty_table()
                    _safe_close_table(table)
                    table = conn.open_table(self._collection_name)

                    # 重建后，检查是否应包含向量
                    # 获取当前表 schema
                    df = table.search().limit(1).to_pandas()
                    if not df.empty and "vector" not in df.columns:
                        # 新表没有向量列，从记录中移除向量
                        record_without_vector = {
                            k: v for k, v in record.items() if k != "vector"
                        }
                        table.add([record_without_vector])
                    else:
                        table.add([record])
            finally:
                _safe_close_table(table)

            return MemoryResponse(success=True, memory_id=data["id"])

        except Exception as e:
            logger.error(f"Failed to add memory note {note.id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to add memory: {str(e)}",
                memory_id=note.id,
            )

    def get(self, note_id: str) -> MemoryResponse:
        """根据 ID 检索一条记忆。"""
        table = None
        try:
            table = self._vector_store.get_raw_connection().open_table(
                self._collection_name
            )

            # 按 ID 搜索
            results = table.search().where(f"id = '{note_id}'").to_pandas()

            if len(results) == 0:
                return MemoryResponse(
                    success=False,
                    error="Memory not found",
                    memory_id=note_id,
                )

            # 转换为 MemoryNote
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
        finally:
            _safe_close_table(table)

    def update(self, note: MemoryNote) -> MemoryResponse:
        """更新一条已有的记忆记录。"""
        try:
            # 检查记忆是否存在
            get_response = self.get(note.id)
            if not get_response.success:
                return MemoryResponse(
                    success=False,
                    error="Memory not found",
                    memory_id=note.id,
                )

            # 删除旧记录
            self.delete(note.id)

            # 添加更新后的记录
            return self.add(note)

        except Exception as e:
            logger.error(f"Failed to update memory note {note.id}: {e}")
            return MemoryResponse(
                success=False,
                error=f"Failed to update memory: {str(e)}",
                memory_id=note.id,
            )

    def delete(self, note_id: str) -> MemoryResponse:
        """根据 ID 删除一条记忆。"""
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
        """按查询文本搜索记忆，支持可选过滤条件。"""
        table = None
        try:
            table = self._vector_store.get_raw_connection().open_table(
                self._collection_name
            )
            results = []

            # 优先尝试向量搜索
            try:
                query_embedding = self._get_embedding(query)
                if query_embedding:
                    # 检查向量列是否存在且维度匹配
                    sample_df = table.search().limit(1).to_pandas()
                    if not sample_df.empty and "vector" in sample_df.columns:
                        # 尝试向量搜索
                        try:
                            vector_df = (
                                table.search(
                                    query_embedding, vector_column_name="vector"
                                )
                                .limit(k)
                                .to_pandas()
                            )

                            for _, row in vector_df.iterrows():
                                # 检查相似度阈值
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

                                # 也对向量搜索结果应用元数据过滤
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

            # 如果向量搜索无结果或失败，回退到文本搜索
            if not results:
                # 文本搜索
                df = table.search().to_pandas()

                # 按查询文本过滤并应用过滤条件
                for _, row in df.iterrows():
                    text = row.get("text", "")
                    metadata = row.get("metadata", "{}")

                    try:
                        metadata_dict = json.loads(metadata)
                    except (json.JSONDecodeError, TypeError):
                        metadata_dict = {}

                    # 应用元数据过滤（如果指定）
                    if filters:
                        filter_match = self._apply_text_search_filters(
                            metadata_dict, filters
                        )
                        if not filter_match:
                            continue

                    # 简单文本匹配
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
        finally:
            _safe_close_table(table)

    def clear(self) -> None:
        """清空存储中的所有记忆。"""
        try:
            self._vector_store.clear()
        except Exception as e:
            logger.error(f"Failed to clear memory store: {e}")

    def list_all(self, filters: Optional[dict[str, Any]] = None) -> List[MemoryNote]:
        """List all memory notes with optional filtering."""
        try:
            # Use empty query to get all results
            return self.search(query="", k=10000, filters=filters or {})
        except Exception as e:
            logger.error(f"Failed to list all memories: {e}")
            return []

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the memory store."""
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
                "memory_store_type": "lancedb",
            }
        except Exception as e:
            logger.error(f"Failed to get memory stats: {e}")
            return {
                "total_count": 0,
                "category_counts": {},
                "tag_counts": {},
                "memory_store_type": "lancedb",
                "error": str(e),
            }
