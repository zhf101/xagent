"""把召回结果组装成 SQL 生成 Prompt。"""

from __future__ import annotations

from typing import Any

from ...web.models.vanna import VannaKnowledgeBase
from .contracts import RetrievalHit, RetrievalResult


class PromptBuilder:
    """面向第一版 ask 的 Prompt 装配器。"""

    def build_prompt(
        self,
        *,
        kb: VannaKnowledgeBase,
        question: str,
        retrieval: RetrievalResult,
        live_schema_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """返回 system/user prompt 以及可直接给 LLM 的 messages。"""
        system_prompt = self._build_system_prompt(kb=kb)
        user_prompt = self._build_user_prompt(
            kb=kb,
            question=question,
            retrieval=retrieval,
            live_schema_context=live_schema_context,
        )
        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "snapshot": {
                "kb_id": int(kb.id),
                "kb_code": kb.kb_code,
                "datasource_id": int(kb.datasource_id),
                "system_short": kb.system_short,
                "env": kb.env,
                "sql_hit_ids": [hit.entry_id for hit in retrieval.sql_hits],
                "schema_hit_ids": [hit.entry_id for hit in retrieval.schema_hits],
                "doc_hit_ids": [hit.entry_id for hit in retrieval.doc_hits],
                "live_schema_source": (
                    str(live_schema_context.get("source"))
                    if live_schema_context
                    and isinstance(live_schema_context.get("source"), str)
                    else None
                ),
                "live_schema_table_names": list(
                    live_schema_context.get("selected_table_names") or []
                )
                if live_schema_context
                else [],
                "live_schema_table_count": (
                    int(live_schema_context.get("table_count") or 0)
                    if live_schema_context
                    else 0
                ),
            },
        }

    def _build_system_prompt(self, *, kb: VannaKnowledgeBase) -> str:
        return (
            "你是严格的 Text2SQL 生成器。"
            f"当前数据库方言是 {kb.dialect or kb.db_type or 'sql'}。"
            "只能生成只读 SQL，不允许 DDL/DML。"
            "如果上下文不足以生成可靠 SQL，返回空 sql。"
            "必须只返回 JSON 对象，不要返回 markdown。"
            'JSON 格式为 {"sql": "...", "confidence": 0.0, "notes": "..."}。'
        )

    def _build_user_prompt(
        self,
        *,
        kb: VannaKnowledgeBase,
        question: str,
        retrieval: RetrievalResult,
        live_schema_context: dict[str, Any] | None = None,
    ) -> str:
        sections = [
            "## 数据源上下文",
            f"- datasource_id: {int(kb.datasource_id)}",
            f"- system_short: {kb.system_short}",
            f"- env: {kb.env}",
            f"- dialect: {kb.dialect or kb.db_type or 'unknown'}",
            "",
            "## SQL 样例",
            self._render_hits(
                retrieval.sql_hits,
                formatter=self._format_question_sql_hit,
            ),
            "",
            "## Schema 摘要",
            self._render_hits(
                retrieval.schema_hits,
                formatter=self._format_doc_like_hit,
            ),
        ]
        if live_schema_context and str(live_schema_context.get("text") or "").strip():
            sections.extend(
                [
                    "",
                    "## 实时 Schema / DDL（数据源直连回退）",
                    str(live_schema_context["text"]).strip(),
                ]
            )
        sections.extend(
            [
                "",
                "## 业务文档",
                self._render_hits(
                    retrieval.doc_hits,
                    formatter=self._format_doc_like_hit,
                ),
                "",
                "## 用户问题",
                question.strip(),
                "",
                "请根据以上上下文输出最终 SQL。",
            ]
        )
        return "\n".join(sections).strip()

    def _render_hits(
        self,
        hits: list[RetrievalHit],
        *,
        formatter,
    ) -> str:
        if not hits:
            return "无"
        return "\n\n".join(
            formatter(hit=hit, index=idx) for idx, hit in enumerate(hits, start=1)
        )

    def _format_question_sql_hit(self, *, hit: RetrievalHit, index: int) -> str:
        parts = [f"{index}. 标题: {hit.title or '未命名样例'}"]
        if hit.question_text:
            parts.append(f"问题: {hit.question_text}")
        if hit.sql_text:
            parts.append("SQL:")
            parts.append(hit.sql_text)
        if hit.doc_text:
            parts.append(f"补充说明: {hit.doc_text}")
        return "\n".join(parts)

    def _format_doc_like_hit(self, *, hit: RetrievalHit, index: int) -> str:
        parts = [f"{index}. 标题: {hit.title or '未命名条目'}"]
        if hit.schema_name or hit.table_name:
            parts.append(
                "定位: "
                f"{hit.schema_name or 'default'}.{hit.table_name or 'unknown'}"
            )
        if hit.doc_text:
            parts.append(hit.doc_text)
        elif hit.chunk_text:
            parts.append(hit.chunk_text)
        return "\n".join(parts)
