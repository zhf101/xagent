"""HTTP 资产 ANN 粗召回器。

用向量相似度替换原来的全量加载 + 线性扫描，作为两阶段匹配漏斗的第一阶段。
向量表不存在或 embedding 不可用时，fallback 到全量加载，保证向后兼容。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xagent.datamakepool.assets.repositories import HttpAssetRepository

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_http_asset_vectors"


class HttpAssetRetriever:
    """基于 LanceDB ANN 的 HTTP 资产粗召回器。"""

    def __init__(
        self,
        db_dir: str,
        embedding_model: Any,
        repository: "HttpAssetRepository",
    ):
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._repository = repository
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
        system_short: str | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[int] = set()

        def _run(search_builder: Any) -> None:
            try:
                df = search_builder.to_pandas()
                for _, row in df.iterrows():
                    aid = int(row["asset_id"])
                    if aid not in seen and aid != 0:
                        seen.add(aid)
                        results.append(
                            {
                                "asset_id": aid,
                                "_distance": float(row.get("_distance", 1.0)),
                            }
                        )
            except Exception:
                logger.warning("ANN 检索子查询失败", exc_info=True)

        half = max(top_k // 2, 1)

        if system_short:
            try:
                domain_search = (
                    table.search(query_vec, vector_column_name="vector")
                    .where(f"system_short = '{system_short}'")
                    .limit(half)
                )
                _run(domain_search)
            except Exception:
                logger.warning("域内 ANN 检索失败，跳过", exc_info=True)

        global_search = (
            table.search(query_vec, vector_column_name="vector")
            .limit(top_k)
        )
        _run(global_search)

        return results

    def recall(
        self,
        query: str,
        system_short: str | None = None,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """召回与查询语义相近的 HTTP 资产候选集。

        返回值：含 asset_id 和 _distance 字段的列表。
        调用方应在此基础上做精确路径匹配或关键词精排后再返回最终结果。

        Fallback 条件（任一满足即 fallback）：
        - 向量表不存在（尚未建索引）
        - embedding 模型不可用
        - 查询向量生成失败
        Fallback 行为：返回全量 active HTTP 资产列表，每条补充 _distance=0.5。
        """
        query_vec = self._get_embedding(query)
        table = self._open_table()

        if query_vec is None or table is None:
            logger.info(
                "HttpAssetRetriever fallback 到全量加载",
                extra={"reason": "no_vector" if query_vec is None else "no_table"},
            )
            return self._fallback(system_short)

        recalled = self._ann_search(table, query_vec, system_short, top_k)
        if not recalled:
            return self._fallback(system_short)

        return recalled

    def _fallback(self, system_short: str | None) -> list[dict[str, Any]]:
        assets = self._repository.list_active_http_assets(system_short=system_short)
        return [{"asset_id": a.id, "_distance": 0.5} for a in assets]
