"""存量场景 ANN 粗召回器。

用向量相似度替换原来的全量加载 + 关键词打分，作为两阶段匹配漏斗的第一阶段。
向量表不存在或 embedding 不可用时，fallback 到调用方传入的全量候选列表。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_legacy_scenario_vectors"


class LegacyScenarioRetriever:
    """基于 LanceDB ANN 的存量场景粗召回器。"""

    def __init__(self, db_dir: str, embedding_model: Any):
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._conn: Any = None

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
            logger.warning("embedding 生成失败，将 fallback 到全量加载", exc_info=True)
            return None

    def _open_table(self) -> Any | None:
        try:
            return self._get_conn().open_table(COLLECTION_NAME)
        except Exception:
            return None

    def _ann_search(
        self,
        table: Any,
        query_vec: list[float],
        top_k: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _run(search_builder: Any) -> None:
            try:
                df = search_builder.to_pandas()
                for _, row in df.iterrows():
                    sid = str(row["scenario_id"])
                    if sid and sid not in seen:
                        seen.add(sid)
                        results.append(
                            {
                                "scenario_id": sid,
                                "_distance": float(row.get("_distance", 1.0)),
                            }
                        )
            except Exception:
                logger.warning("ANN 检索子查询失败", exc_info=True)

        global_search = (
            table.search(query_vec, vector_column_name="vector")
            .limit(top_k)
        )
        _run(global_search)
        return results

    def recall(
        self,
        query: str,
        top_k: int = 20,
        fallback_entries: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """召回与查询语义相近的存量场景候选集。

        返回值：含 scenario_id 和 _distance 字段的列表。
        调用方应在此基础上做关键词精排后再返回最终结果。

        Fallback 条件（任一满足即 fallback）：
        - 向量表不存在（尚未建索引）
        - embedding 模型不可用
        - 查询向量生成失败
        Fallback 行为：将 fallback_entries（全量 catalog）转为含 _distance=0.5 的列表返回。
        """
        query_vec = self._get_embedding(query)
        table = self._open_table()

        if query_vec is None or table is None:
            logger.info(
                "LegacyScenarioRetriever fallback 到全量加载",
                extra={"reason": "no_vector" if query_vec is None else "no_table"},
            )
            return self._fallback(fallback_entries)

        recalled = self._ann_search(table, query_vec, top_k)
        if not recalled:
            return self._fallback(fallback_entries)

        return recalled

    def _fallback(
        self, fallback_entries: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        if not fallback_entries:
            return []
        return [
            {"scenario_id": e["scenario_id"], "_distance": 0.5}
            for e in fallback_entries
            if e.get("scenario_id")
        ]
