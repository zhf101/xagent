"""SQL Brain 的 LanceDB 存储实现。

这个实现复用项目现有的 LanceDB 连接管理与 embedding 适配器，
为 SQL Brain 提供持久化训练与向量召回能力。
"""

from __future__ import annotations

import json
import logging
from hashlib import sha1
from dataclasses import asdict
from typing import Any

from .models import RetrievedDDL, RetrievedDocumentation, RetrievedQuestionSql

logger = logging.getLogger(__name__)

QUESTION_SQL_TABLE = "datamakepool_sql_brain_question_sql_vectors"
DDL_TABLE = "datamakepool_sql_brain_ddl_vectors"
DOC_TABLE = "datamakepool_sql_brain_doc_vectors"


def _escape_lancedb_string(value: str) -> str:
    """最小转义，避免 where/delete 表达式里的单引号破坏语法。"""

    return value.replace("'", "''")


def _stable_digest(text: str) -> str:
    """生成跨进程稳定的记录摘要。"""

    return sha1(text.encode("utf-8")).hexdigest()


class LanceDBSqlBrainStore:
    """基于 LanceDB 的 SQL Brain 训练与检索存储。"""

    def __init__(self, db_dir: str, embedding_model: Any):
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._conn: Any = None

    @property
    def retrieval_mode(self) -> str:
        return "vector"

    @property
    def embedding_enabled(self) -> bool:
        return self._embedding_model is not None

    def _get_conn(self) -> Any:
        if self._conn is None:
            from xagent.providers.vector_store.lancedb import LanceDBConnectionManager

            self._conn = LanceDBConnectionManager().get_connection(self._db_dir)
        return self._conn

    def _get_embedding(self, text: str) -> list[float] | None:
        if not self._embedding_model or not text.strip():
            return None
        try:
            result = self._embedding_model.encode(text)
            if isinstance(result, list) and result:
                if isinstance(result[0], (int, float)):
                    return result  # type: ignore[return-value]
                if isinstance(result[0], list):
                    return result[0]
            return None
        except Exception:
            logger.warning("SQL Brain embedding 生成失败", exc_info=True)
            return None

    def _create_table(self, table_name: str) -> Any:
        conn = self._get_conn()
        sample_vec = self._get_embedding("sample vector")
        sample = [
            {
                "id": "__init__",
                "system_short": "",
                "db_type": "",
                "text": "sample vector",
                "payload": "{}",
                "vector": sample_vec or [0.0, 0.0, 0.0],
            }
        ]
        table = conn.create_table(table_name, data=sample)
        table.delete("id = '__init__'")
        return table

    def _get_table(self, table_name: str) -> Any | None:
        try:
            return self._get_conn().open_table(table_name)
        except Exception:
            try:
                return self._create_table(table_name)
            except Exception:
                logger.warning("SQL Brain 打开/创建向量表失败: %s", table_name, exc_info=True)
                return None

    def _build_filter_expr(
        self,
        *,
        system_short: str | None,
        db_type: str | None,
    ) -> str | None:
        clauses: list[str] = []
        if system_short:
            clauses.append(
                f"system_short = '{_escape_lancedb_string(str(system_short))}'"
            )
        if db_type:
            clauses.append(f"db_type = '{_escape_lancedb_string(str(db_type))}'")
        return " AND ".join(clauses) if clauses else None

    def _search_payloads(
        self,
        table_name: str,
        query: str,
        *,
        system_short: str | None,
        db_type: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        query_vec = self._get_embedding(query)
        table = self._get_table(table_name)
        if query_vec is None or table is None:
            return []

        try:
            search_builder = table.search(query_vec, vector_column_name="vector")
            filter_expr = self._build_filter_expr(
                system_short=system_short,
                db_type=db_type,
            )
            if filter_expr:
                search_builder = search_builder.where(filter_expr)
            df = search_builder.limit(top_k).to_pandas()
        except Exception:
            logger.warning("SQL Brain ANN 检索失败: %s", table_name, exc_info=True)
            return []

        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            try:
                payload = json.loads(str(row.get("payload") or "{}"))
                payload["score"] = max(0.0, 1.0 - float(row.get("_distance", 1.0)))
                results.append(payload)
            except Exception:
                logger.warning("SQL Brain 检索结果解析失败", exc_info=True)
        return results

    def _upsert_record(
        self,
        table_name: str,
        *,
        record_id: str,
        text: str,
        payload: dict[str, Any],
        system_short: str | None,
        db_type: str | None,
    ) -> None:
        vector = self._get_embedding(text)
        table = self._get_table(table_name)
        if table is None or vector is None:
            return

        record = {
            "id": record_id,
            "system_short": system_short or "",
            "db_type": db_type or "",
            "text": text,
            "payload": json.dumps(payload, ensure_ascii=False),
            "vector": vector,
        }
        table.delete(f"id = '{_escape_lancedb_string(record_id)}'")
        table.add([record])

    def search_question_sql(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedQuestionSql]:
        return [
            RetrievedQuestionSql(**payload)
            for payload in self._search_payloads(
                QUESTION_SQL_TABLE,
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            )
        ]

    def search_ddl(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDDL]:
        return [
            RetrievedDDL(**payload)
            for payload in self._search_payloads(
                DDL_TABLE,
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            )
        ]

    def search_documentation(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedDocumentation]:
        return [
            RetrievedDocumentation(**payload)
            for payload in self._search_payloads(
                DOC_TABLE,
                question,
                system_short=system_short,
                db_type=db_type,
                top_k=top_k,
            )
        ]

    def add_question_sql(self, item: RetrievedQuestionSql) -> None:
        text = f"问题：{item.question}\nSQL：{item.sql}"
        self._upsert_record(
            QUESTION_SQL_TABLE,
            record_id=f"qsql::{item.system_short or 'global'}::{item.db_type or 'all'}::{_stable_digest(text)}",
            text=text,
            payload=asdict(item),
            system_short=item.system_short,
            db_type=item.db_type,
        )

    def add_ddl(self, item: RetrievedDDL) -> None:
        text = f"表：{item.table_name}\nDDL：{item.ddl}"
        self._upsert_record(
            DDL_TABLE,
            record_id=f"ddl::{item.system_short or 'global'}::{item.db_type or 'all'}::{_stable_digest(text)}",
            text=text,
            payload=asdict(item),
            system_short=item.system_short,
            db_type=item.db_type,
        )

    def add_documentation(self, item: RetrievedDocumentation) -> None:
        self._upsert_record(
            DOC_TABLE,
            record_id=f"doc::{item.system_short or 'global'}::{item.db_type or 'all'}::{_stable_digest(item.content)}",
            text=item.content,
            payload=asdict(item),
            system_short=item.system_short,
            db_type=item.db_type,
        )
