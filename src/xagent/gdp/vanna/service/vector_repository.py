"""Vanna 向量仓储。

这里不是新的 provider，也不是新的检索算法层，
而是 Vanna 业务和统一 `providers/vector_store` 之间的最薄桥接层。

它只负责三件事：

1. 把 Vanna 的 chunk 业务主键映射成 provider 可识别的向量记录
2. 统一 collection 命名、metadata 结构和 id 约定
3. 把 provider 返回结果重新翻译回 `chunk_id` 语义
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from xagent.core.model.embedding.base import BaseEmbedding
from xagent.gdp.vanna.model.vanna import VannaEmbeddingChunk, VannaKnowledgeBase
from xagent.providers.vector_store import VectorStore, create_vector_store
from xagent.web.models.model import Model
from xagent.web.models.user import UserModel
from xagent.web.services.llm_utils import _create_embedding_instance
from xagent.web.services.model_service import (
    get_default_embedding_model,
    get_embedding_model,
)


def _load_accessible_embedding_model(
    db: Session,
    *,
    model_identifier: str,
    owner_user_id: int | None,
) -> Model | None:
    """按 `model_id / model_name` 解析 embedding 模型。

    这里显式限制为“当前用户可见或共享”的模型，避免知识库里写了一个任意字符串后，
    后端悄悄解析成并不属于当前用户的配置。
    """
    normalized_identifier = str(model_identifier or "").strip()
    if not normalized_identifier:
        return None

    query = (
        db.query(Model)
        .outerjoin(UserModel, UserModel.model_id == Model.id)
        .filter(Model.category == "embedding", Model.is_active.is_(True))
        .filter(
            or_(
                Model.model_id == normalized_identifier,
                Model.model_name == normalized_identifier,
            )
        )
    )
    if owner_user_id is not None:
        query = query.filter(
            or_(
                UserModel.user_id == int(owner_user_id),
                UserModel.is_shared.is_(True),
            )
        )
    return query.first()


def resolve_vanna_embedding_runtime(
    db: Session,
    *,
    kb: VannaKnowledgeBase,
    owner_user_id: int | None,
) -> tuple[BaseEmbedding | None, str | None]:
    """解析 Vanna 当前应使用的 embedding 运行时。

    优先级按已经确认的业务规则执行：
    1. `kb.embedding_model`
    2. 当前用户默认 embedding model

    注意这里返回的是“可真正拿来编码的实例 + 稳定模型标识”，
    后续索引和检索都共用这对结果，避免名字和实例来源不一致。
    """
    preferred_identifier = str(kb.embedding_model or "").strip() or None
    if preferred_identifier:
        preferred_row = _load_accessible_embedding_model(
            db,
            model_identifier=preferred_identifier,
            owner_user_id=owner_user_id,
        )
        if preferred_row is not None:
            return _create_embedding_instance(preferred_row), str(preferred_row.model_id)

    return get_embedding_model(owner_user_id), get_default_embedding_model(owner_user_id)


class VannaVectorRepository:
    """Vanna 业务向量仓储。"""

    def __init__(
        self,
        *,
        vector_store_factory: Callable[..., VectorStore] = create_vector_store,
    ) -> None:
        self.vector_store_factory = vector_store_factory

    def index_chunks(
        self,
        *,
        chunk_vectors: Iterable[tuple[VannaEmbeddingChunk, list[float]]],
    ) -> None:
        """把已生成好的 chunk 向量写入统一 provider。"""
        grouped_payloads: dict[str, list[tuple[VannaEmbeddingChunk, list[float]]]] = (
            defaultdict(list)
        )

        for chunk_row, vector in chunk_vectors:
            if not vector or chunk_row.id is None:
                continue
            grouped_payloads[self._collection_name(chunk_row)].append((chunk_row, vector))

        for collection_name, payloads in grouped_payloads.items():
            store = self.vector_store_factory(collection_name=collection_name)
            vector_ids = [self._vector_id(chunk_row.id) for chunk_row, _ in payloads]
            store.delete_vectors(vector_ids)
            store.add_vectors(
                vectors=[vector for _, vector in payloads],
                ids=vector_ids,
                metadatas=[
                    self._metadata_from_chunk(chunk_row)
                    for chunk_row, _ in payloads
                ],
            )

    def delete_chunks(self, chunks: Iterable[VannaEmbeddingChunk]) -> None:
        """按 chunk 删除 provider 记录。"""
        grouped_ids: dict[str, list[str]] = defaultdict(list)
        for chunk_row in chunks:
            if chunk_row.id is None:
                continue
            grouped_ids[self._collection_name(chunk_row)].append(
                self._vector_id(chunk_row.id)
            )

        for collection_name, ids in grouped_ids.items():
            if not ids:
                continue
            store = self.vector_store_factory(collection_name=collection_name)
            if not store.delete_vectors(ids):
                raise RuntimeError(
                    f"Failed to delete Vanna vectors for collection {collection_name}"
                )

    def search_chunks(
        self,
        *,
        kb_id: int,
        chunk_type: str,
        query_vector: list[float],
        top_k: int,
        system_short: str | None = None,
        env: str | None = None,
        lifecycle_statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按 bucket 查询候选 chunk。

        返回值里保留 provider 原始分和一个稳定的 `rank_score`。
        GDP 业务层后续只依赖顺序信号做重排，不依赖各后端 score 的绝对语义。
        """
        filters: dict[str, Any] = {
            "domain": "vanna",
            "kb_id": int(kb_id),
            "chunk_type": str(chunk_type),
        }
        if system_short:
            filters["system_short"] = str(system_short)
        if env:
            filters["env"] = str(env)

        statuses = [str(item) for item in list(lifecycle_statuses or []) if str(item).strip()]
        hits = self.vector_store_factory(
            collection_name=self._collection_name_from_values(kb_id, chunk_type)
        ).search_vectors(
            query_vector=query_vector,
            top_k=max(int(top_k), 1),
            filters=filters,
        )

        if statuses:
            hits = [
                hit
                for hit in hits
                if str((hit.get("metadata") or {}).get("lifecycle_status") or "")
                in statuses
            ]

        normalized_hits: list[dict[str, Any]] = []
        max_rank = max(len(hits), 1)
        for rank, hit in enumerate(hits, start=1):
            metadata = dict(hit.get("metadata") or {})
            chunk_id = metadata.get("chunk_id")
            if chunk_id is None:
                continue
            normalized_hits.append(
                {
                    "chunk_id": int(chunk_id),
                    "provider_score": float(hit.get("score") or 0.0),
                    "rank_score": round((max_rank - rank + 1) / max_rank, 6),
                }
            )
        return normalized_hits

    def _collection_name(self, chunk_row: VannaEmbeddingChunk) -> str:
        return self._collection_name_from_values(chunk_row.kb_id, chunk_row.chunk_type)

    def _collection_name_from_values(self, kb_id: int, chunk_type: str) -> str:
        return f"vanna_kb_{int(kb_id)}_{str(chunk_type)}"

    def _vector_id(self, chunk_id: int) -> str:
        return f"vanna_chunk_{int(chunk_id)}"

    def _metadata_from_chunk(self, chunk_row: VannaEmbeddingChunk) -> dict[str, Any]:
        """统一生成 provider metadata。

        metadata 只保留 provider 检索和排障真正需要的最小字段，
        避免把整行业务数据重复写进向量库，导致两边定义长期漂移。
        """
        return {
            "domain": "vanna",
            "kb_id": int(chunk_row.kb_id),
            "entry_id": int(chunk_row.entry_id),
            "chunk_id": int(chunk_row.id),
            "chunk_type": str(chunk_row.chunk_type),
            "system_short": chunk_row.system_short,
            "env": chunk_row.env,
            "lifecycle_status": chunk_row.lifecycle_status,
            "text": chunk_row.embedding_text or chunk_row.chunk_text or "",
        }
