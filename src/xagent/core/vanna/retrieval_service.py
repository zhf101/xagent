"""Vanna 训练切片检索服务。"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from sqlalchemy.orm import Session

from ...core.model.embedding.base import BaseEmbedding
from ...web.models.vanna import VannaEmbeddingChunk, VannaTrainingEntry
from .contracts import RetrievalHit, RetrievalResult


class RetrievalService:
    """按桶召回 `question_sql / schema_summary / documentation`。"""

    def __init__(
        self,
        db: Session,
        *,
        embedding_model: BaseEmbedding | None = None,
        embedding_model_name: str | None = None,
    ) -> None:
        self.db = db
        self.embedding_model = embedding_model
        self.embedding_model_name = embedding_model_name

    def retrieve(
        self,
        *,
        kb_id: int,
        question: str,
        system_short: str | None = None,
        env: str | None = None,
        top_k_sql: int = 8,
        top_k_schema: int = 12,
        top_k_doc: int = 6,
        lifecycle_statuses: list[str] | None = None,
    ) -> RetrievalResult:
        """执行一次按桶召回。"""
        statuses = list(lifecycle_statuses or ["published"])
        query_text = str(question or "").strip()
        query_vector = self._encode_query(query_text)

        sql_hits = self._search_bucket(
            kb_id=kb_id,
            question=query_text,
            query_vector=query_vector,
            chunk_type="question_sql_pair",
            limit=top_k_sql,
            system_short=system_short,
            env=env,
            lifecycle_statuses=statuses,
        )
        schema_hits = self._search_bucket(
            kb_id=kb_id,
            question=query_text,
            query_vector=query_vector,
            chunk_type="schema_table_summary",
            limit=top_k_schema,
            system_short=system_short,
            env=env,
            lifecycle_statuses=statuses,
        )
        doc_hits = self._search_bucket(
            kb_id=kb_id,
            question=query_text,
            query_vector=query_vector,
            chunk_type="documentation",
            limit=top_k_doc,
            system_short=system_short,
            env=env,
            lifecycle_statuses=statuses,
        )
        return RetrievalResult(
            query_text=query_text,
            sql_hits=sql_hits,
            schema_hits=schema_hits,
            doc_hits=doc_hits,
            used_embedding=query_vector is not None,
        )

    def _search_bucket(
        self,
        *,
        kb_id: int,
        question: str,
        query_vector: list[float] | None,
        chunk_type: str,
        limit: int,
        system_short: str | None,
        env: str | None,
        lifecycle_statuses: list[str],
    ) -> list[RetrievalHit]:
        if limit <= 0:
            return []

        query = (
            self.db.query(VannaEmbeddingChunk, VannaTrainingEntry)
            .join(VannaTrainingEntry, VannaEmbeddingChunk.entry_id == VannaTrainingEntry.id)
            .filter(
                VannaEmbeddingChunk.kb_id == int(kb_id),
                VannaEmbeddingChunk.chunk_type == chunk_type,
                VannaEmbeddingChunk.lifecycle_status.in_(lifecycle_statuses),
                VannaTrainingEntry.lifecycle_status.in_(lifecycle_statuses),
            )
        )
        if system_short:
            query = query.filter(VannaEmbeddingChunk.system_short == system_short)
        if env:
            query = query.filter(VannaEmbeddingChunk.env == env)
        if query_vector is not None and self.embedding_model_name:
            query = query.filter(VannaEmbeddingChunk.embedding_model == self.embedding_model_name)

        rows = query.order_by(VannaEmbeddingChunk.id.asc()).all()
        hits: list[RetrievalHit] = []
        for chunk_row, entry_row in rows:
            scored = self._score_hit(
                question=question,
                query_vector=query_vector,
                chunk_row=chunk_row,
                entry_row=entry_row,
            )
            if scored is not None:
                hits.append(scored)

        hits.sort(key=lambda item: (item.score, -item.chunk_id), reverse=True)
        return hits[:limit]

    def _score_hit(
        self,
        *,
        question: str,
        query_vector: list[float] | None,
        chunk_row: VannaEmbeddingChunk,
        entry_row: VannaTrainingEntry,
    ) -> RetrievalHit | None:
        lexical_score, lexical_reasons = self._compute_lexical_score(
            question,
            "\n".join(
                item
                for item in [
                    chunk_row.chunk_text or "",
                    entry_row.title or "",
                    entry_row.question_text or "",
                    entry_row.doc_text or "",
                    entry_row.schema_name or "",
                    entry_row.table_name or "",
                ]
                if item and item.strip()
            ),
        )

        vector_score = 0.0
        vector = self._parse_vector_literal(chunk_row.embedding_vector)
        if query_vector is not None and vector is not None:
            vector_score = self._cosine_similarity(query_vector, vector)

        total_score = (
            0.7 * vector_score + 0.3 * lexical_score if query_vector else lexical_score
        )
        if total_score <= 0:
            return None

        reasons = list(lexical_reasons)
        if vector_score > 0:
            reasons.append(f"向量相似度 {vector_score:.3f}")

        return RetrievalHit(
            entry_id=int(entry_row.id),
            chunk_id=int(chunk_row.id),
            entry_type=str(entry_row.entry_type),
            chunk_type=str(chunk_row.chunk_type),
            score=round(total_score, 6),
            title=entry_row.title,
            chunk_text=chunk_row.chunk_text,
            question_text=entry_row.question_text,
            sql_text=entry_row.sql_text,
            doc_text=entry_row.doc_text,
            schema_name=entry_row.schema_name,
            table_name=entry_row.table_name,
            metadata={
                "entry_code": entry_row.entry_code,
                "embedding_model": chunk_row.embedding_model,
                "vector_score": round(vector_score, 6),
                "lexical_score": round(lexical_score, 6),
            },
            reasons=reasons,
        )

    def _encode_query(self, text: str) -> list[float] | None:
        if self.embedding_model is None or not text.strip():
            return None
        raw = self.embedding_model.encode(text)
        if not isinstance(raw, list):
            return None
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        vector = [float(item) for item in raw]
        return vector or None

    def _compute_lexical_score(
        self, question: str, candidate_text: str
    ) -> tuple[float, list[str]]:
        query_tokens = self._tokenize(question)
        candidate_tokens = self._tokenize(candidate_text)
        if not query_tokens or not candidate_tokens:
            return 0.0, []

        overlap = query_tokens & candidate_tokens
        if not overlap:
            return 0.0, []

        coverage = len(overlap) / max(1, len(query_tokens))
        density = len(overlap) / max(1, len(candidate_tokens))
        score = min(1.0, 0.8 * coverage + 0.2 * min(1.0, density * 4))
        reasons = ["关键词命中: " + " / ".join(sorted(list(overlap))[:5])]
        return score, reasons

    def _tokenize(self, text: str) -> set[str]:
        normalized = str(text or "").lower()
        tokens: set[str] = set()
        for match in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized):
            if not match:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                tokens.update({char for char in match if char.strip()})
                if len(match) > 1:
                    tokens.update(match[idx : idx + 2] for idx in range(len(match) - 1))
            else:
                tokens.add(match)
        return {token for token in tokens if token}

    def _parse_vector_literal(self, payload: Any) -> list[float] | None:
        if payload is None:
            return None
        if isinstance(payload, list):
            try:
                return [float(item) for item in payload]
            except (TypeError, ValueError):
                return None
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return None
            if isinstance(data, list):
                try:
                    return [float(item) for item in data]
                except (TypeError, ValueError):
                    return None
        return None

    def _cosine_similarity(
        self, left: list[float] | None, right: list[float] | None
    ) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(left_item * right_item for left_item, right_item in zip(left, right))
        left_norm = math.sqrt(sum(item * item for item in left))
        right_norm = math.sqrt(sum(item * item for item in right))
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))
