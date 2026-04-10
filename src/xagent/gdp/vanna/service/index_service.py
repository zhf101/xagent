"""把训练知识条目固化成检索切片。

这个模块解决的是“训练条目如何变成可检索单元”。
训练条目更像原始知识文档，而 embedding chunk 才是检索时真正扫描的对象。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from xagent.core.model.embedding.base import BaseEmbedding
from xagent.gdp.vanna.model.vanna import (
    VannaEmbeddingChunk,
    VannaKnowledgeBase,
    VannaTrainingEntry,
)
from .errors import VannaTrainingEntryNotFoundError
from .vector_repository import VannaVectorRepository


class IndexService:
    """负责生成 `vanna_embedding_chunks`。"""

    def __init__(
        self,
        db: Session,
        *,
        embedding_model: BaseEmbedding | None = None,
        embedding_model_name: str | None = None,
        vector_repository: VannaVectorRepository | None = None,
    ) -> None:
        self.db = db
        self.embedding_model = embedding_model
        self.embedding_model_name = embedding_model_name
        self.vector_repository = vector_repository or VannaVectorRepository()

    def reindex_entry(self, *, entry_id: int) -> list[VannaEmbeddingChunk]:
        """重建单条训练知识的切片。

        状态影响：
        - 会删除该 entry 旧的全部 chunk
        - 会重新生成并落库新的 chunk
        - 会更新知识库的 `last_train_at`
        """
        entry = self.db.get(VannaTrainingEntry, int(entry_id))
        if entry is None:
            raise VannaTrainingEntryNotFoundError(
                f"Training entry {entry_id} was not found"
            )

        existing_chunks = (
            self.db.query(VannaEmbeddingChunk)
            .filter(VannaEmbeddingChunk.entry_id == int(entry_id))
            .all()
        )
        if existing_chunks:
            self.vector_repository.delete_chunks(existing_chunks)

        (
            self.db.query(VannaEmbeddingChunk)
            .filter(VannaEmbeddingChunk.entry_id == int(entry_id))
            .delete(synchronize_session=False)
        )

        created_rows: list[VannaEmbeddingChunk] = []
        created_vectors: list[tuple[VannaEmbeddingChunk, list[float]]] = []
        for order, spec in enumerate(self._build_chunk_specs(entry)):
            chunk_text = str(spec["chunk_text"]).strip()
            if not chunk_text:
                continue

            embedding_text = str(spec.get("embedding_text") or chunk_text).strip()
            vector = self._encode_embedding_if_needed(embedding_text)
            row = VannaEmbeddingChunk(
                kb_id=int(entry.kb_id),
                datasource_id=int(entry.datasource_id),
                entry_id=int(entry.id),
                system_short=entry.system_short,
                env=entry.env,
                source_table="vanna_training_entries",
                source_row_id=int(entry.id),
                chunk_type=str(spec["chunk_type"]),
                chunk_order=order,
                chunk_text=chunk_text,
                embedding_text=embedding_text,
                embedding_model=self.embedding_model_name,
                embedding_dim=len(vector) if vector else None,
                embedding_vector=None,
                distance_metric="cosine" if vector else None,
                token_count_estimate=self._estimate_token_count(embedding_text),
                lifecycle_status=entry.lifecycle_status,
                metadata_json=dict(spec.get("metadata_json") or {}),
                chunk_hash=self._hash_payload(
                    {
                        "entry_id": int(entry.id),
                        "chunk_type": spec["chunk_type"],
                        "chunk_text": chunk_text,
                        "embedding_text": embedding_text,
                    }
                ),
            )
            self.db.add(row)
            created_rows.append(row)
            if vector:
                created_vectors.append((row, vector))

        # 这里必须先 flush 再写 provider。
        # 因为 provider 里的稳定主键来自 `VannaEmbeddingChunk.id`，
        # 不 flush 就拿不到真正的 chunk_id，后续删除与回表都无法对齐。
        self.db.flush()
        if created_vectors:
            self.vector_repository.index_chunks(chunk_vectors=created_vectors)

        kb = self.db.get(VannaKnowledgeBase, int(entry.kb_id))
        if kb is not None:
            kb.last_train_at = datetime.now(UTC).replace(tzinfo=None)
            if self.embedding_model_name and not kb.embedding_model:
                kb.embedding_model = self.embedding_model_name

        self.db.commit()
        for row in created_rows:
            self.db.refresh(row)
        return created_rows

    def reindex_kb(
        self,
        *,
        kb_id: int,
        lifecycle_statuses: list[str] | None = None,
    ) -> list[VannaEmbeddingChunk]:
        """重建知识库下若干条目的切片。

        这里按 entry 逐条重建而不是写复杂批处理，是为了复用单条重建逻辑并保持行为一致。
        """
        query = self.db.query(VannaTrainingEntry).filter(
            VannaTrainingEntry.kb_id == int(kb_id)
        )
        if lifecycle_statuses:
            query = query.filter(
                VannaTrainingEntry.lifecycle_status.in_(list(lifecycle_statuses))
            )
        entries = query.order_by(VannaTrainingEntry.id.asc()).all()

        created_rows: list[VannaEmbeddingChunk] = []
        for entry in entries:
            created_rows.extend(self.reindex_entry(entry_id=int(entry.id)))
        return created_rows

    def _build_chunk_specs(self, entry: VannaTrainingEntry) -> list[dict[str, Any]]:
        """根据训练条目类型生成切片规格。"""

        if entry.entry_type == "question_sql":
            chunk_text = self._build_question_sql_chunk_text(entry)
            return [
                {
                    "chunk_type": "question_sql_pair",
                    "chunk_text": chunk_text,
                    "embedding_text": chunk_text,
                    "metadata_json": {
                        "entry_type": entry.entry_type,
                        "entry_code": entry.entry_code,
                        "title": entry.title,
                        "schema_name": entry.schema_name,
                        "table_name": entry.table_name,
                    },
                }
            ]

        if entry.entry_type == "schema_summary":
            chunk_text = str(entry.doc_text or "").strip()
            return [
                {
                    "chunk_type": "schema_table_summary",
                    "chunk_text": chunk_text,
                    "embedding_text": "\n".join(
                        item
                        for item in [entry.title or "", chunk_text]
                        if item and item.strip()
                    ).strip(),
                    "metadata_json": {
                        "entry_type": entry.entry_type,
                        "entry_code": entry.entry_code,
                        "schema_name": entry.schema_name,
                        "table_name": entry.table_name,
                    },
                }
            ]

        chunk_text = "\n".join(
            item for item in [entry.title or "", entry.doc_text or ""] if item.strip()
        ).strip()
        return [
            {
                "chunk_type": "documentation",
                "chunk_text": chunk_text,
                "embedding_text": chunk_text,
                "metadata_json": {
                    "entry_type": entry.entry_type,
                    "entry_code": entry.entry_code,
                    "title": entry.title,
                },
            }
        ]

    def _build_question_sql_chunk_text(self, entry: VannaTrainingEntry) -> str:
        """把问答对条目渲染成单个 question/sql 检索片段。"""

        lines = []
        if entry.question_text:
            lines.append(f"问题: {entry.question_text.strip()}")
        if entry.sql_text:
            lines.append("SQL:")
            lines.append(entry.sql_text.strip())
        if entry.sql_explanation:
            lines.append(f"说明: {entry.sql_explanation.strip()}")
        return "\n".join(lines).strip()

    def _encode_embedding_if_needed(self, text: str) -> list[float] | None:
        """按需调用 embedding 模型编码。"""

        if self.embedding_model is None or not text.strip():
            return None
        raw = self.embedding_model.encode(text)
        if not isinstance(raw, list):
            return None
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        vector = [float(item) for item in raw]
        return vector or None

    def _estimate_token_count(self, text: str) -> int:
        """粗略估算 token 数，供诊断和调参使用。"""

        normalized = text.strip()
        if not normalized:
            return 0
        return max(1, math.ceil(len(normalized) / 4))

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        """为 chunk 计算稳定哈希，便于后续去重与问题排查。"""

        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

