"""Vanna 训练切片检索服务。

这个模块的职责很克制：只负责“从已经入库的知识里找候选”，
不负责生成 Prompt，也不负责决定最终 SQL 是否可执行。

当前检索分三桶：
- `question_sql_pair`: 历史问答对，最接近直接复用 SQL
- `schema_table_summary`: 结构摘要，帮助模型理解库表关系
- `documentation`: 业务文档，补齐口径、术语和背景知识
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from xagent.core.model.embedding.base import BaseEmbedding
from xagent.gdp.vanna.model.vanna import VannaEmbeddingChunk, VannaTrainingEntry
from .contracts import RetrievalHit, RetrievalResult
from .vector_repository import VannaVectorRepository


class RetrievalService:
    """按桶召回 `question_sql / schema_summary / documentation`。

    这里采用“词法打分 + 可选向量打分”的混合策略：
    - 没有 embedding 时，仍能靠词法检索工作
    - 有 embedding 时，用向量相似度增强召回鲁棒性
    """

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
        """执行一次按桶召回。

        返回值不是扁平 hits，而是按知识类型分桶后的 `RetrievalResult`。
        这样 PromptBuilder 可以按语义角色来组织上下文，而不是把所有片段混成一堆。
        """
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
        """在指定知识桶里做候选检索并排序。"""

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
        vector_rank_map: dict[int, float] = {}
        if query_vector is not None:
            try:
                vector_hits = self.vector_repository.search_chunks(
                    kb_id=kb_id,
                    chunk_type=chunk_type,
                    query_vector=query_vector,
                    top_k=max(limit * 6, limit),
                    system_short=system_short,
                    env=env,
                    lifecycle_statuses=lifecycle_statuses,
                )
                vector_rank_map = {
                    int(item["chunk_id"]): float(item["rank_score"])
                    for item in vector_hits
                }
            except Exception:
                vector_rank_map = {}
            if vector_rank_map:
                query = query.filter(
                    VannaEmbeddingChunk.id.in_(list(vector_rank_map.keys()))
                )
                if self.embedding_model_name:
                    query = query.filter(
                        VannaEmbeddingChunk.embedding_model == self.embedding_model_name
                    )

        rows = query.order_by(VannaEmbeddingChunk.id.asc()).all()
        hits: list[RetrievalHit] = []
        for chunk_row, entry_row in rows:
            scored = self._score_hit(
                question=question,
                vector_rank_score=float(vector_rank_map.get(int(chunk_row.id), 0.0)),
                used_vector=bool(vector_rank_map),
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
        vector_rank_score: float,
        used_vector: bool,
        chunk_row: VannaEmbeddingChunk,
        entry_row: VannaTrainingEntry,
    ) -> RetrievalHit | None:
        """为单个 chunk 计算综合得分，并组装成命中结果。"""

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

        # 这里不直接信任 provider 的原始 score 数值，
        # 因为不同后端返回的分值语义可能是 cosine distance、L2 distance 或别的度量。
        # GDP 业务层只信任“provider 已经按相似度排好序”这一点，
        # 再把顺序折算成 rank_score 参与重排。
        total_score = (
            0.7 * vector_rank_score + 0.3 * lexical_score
            if used_vector
            else lexical_score
        )
        if total_score <= 0:
            return None

        reasons = list(lexical_reasons)
        if vector_rank_score > 0:
            reasons.append(f"向量召回排序分 {vector_rank_score:.3f}")

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
                "vector_rank_score": round(vector_rank_score, 6),
                "lexical_score": round(lexical_score, 6),
            },
            reasons=reasons,
        )

    def _encode_query(self, text: str) -> list[float] | None:
        """把查询文本编码成向量；编码不可用时返回 `None`。"""

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
        """计算轻量词法分，并给出可解释原因。"""

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
        """把中英文混合文本切成适合粗粒度召回的 token 集。"""

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


