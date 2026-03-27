"""模板 ANN 粗召回器。

用向量相似度替换原来的全量 SQL 加载 + 线性扫描，作为两阶段匹配漏斗的第一阶段。

设计原则：
- 向量表存在时走 ANN 召回（O(log n) 级别）
- 向量表不存在或 embedding 不可用时，fallback 到 TemplateService.list_templates()，
  保证向后兼容，不引入硬依赖
- system_short 非空时，域内召回（where 过滤）和全局召回各取一半，合并去重，
  既保证域内精准又有全局语义兜底
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xagent.datamakepool.templates.service import TemplateService

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_template_vectors"


class TemplateRetriever:
    """基于 LanceDB ANN 的模板粗召回器。"""

    def __init__(
        self,
        db_dir: str,
        embedding_model: Any,
        template_service: TemplateService,
    ):
        """
        Args:
            db_dir: LanceDB 数据目录。
            embedding_model: BaseEmbedding 实例，调用 encode() 方法。
            template_service: 用于 fallback 和 batch_get 加载完整模板详情。
        """
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._template_service = template_service
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
        """打开向量表，不存在时返回 None（触发 fallback）。"""
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
        """执行 ANN 检索，返回含 template_id/_distance 的列表。

        system_short 非空时做两路检索：域内 top_k//2 + 全局 top_k//2，合并去重。
        """
        results: list[dict[str, Any]] = []
        seen: set[int] = set()

        def _run(search_builder: Any) -> None:
            try:
                df = search_builder.to_pandas()
                for _, row in df.iterrows():
                    tid = int(row["template_id"])
                    if tid not in seen and tid != 0:
                        seen.add(tid)
                        results.append(
                            {
                                "template_id": tid,
                                "_distance": float(row.get("_distance", 1.0)),
                            }
                        )
            except Exception:
                logger.warning("ANN 检索子查询失败", exc_info=True)

        half = max(top_k // 2, 1)

        if system_short:
            # 域内召回：优先取同 system_short 的模板
            try:
                domain_search = (
                    table.search(query_vec, vector_column_name="vector")
                    .where(f"system_short = '{system_short}'")
                    .limit(half)
                )
                _run(domain_search)
            except Exception:
                logger.warning("域内 ANN 检索失败，跳过", exc_info=True)

        # 全局召回：不限系统，补充语义相近的跨系统模板
        global_search = (
            table.search(query_vec, vector_column_name="vector")
            .limit(top_k)
        )
        _run(global_search)

        return results

    def recall(
        self,
        user_input: str,
        system_short: str | None = None,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        """召回与用户输入语义相近的模板候选集。

        返回值：含 template_id 和 _distance 字段的列表，不含完整模板详情。
        调用方应用 TemplateService.batch_get() 补全详情后再传给精排层。

        Fallback 条件（任一满足即 fallback）：
        - 向量表不存在（尚未建索引）
        - embedding 模型不可用
        - 查询向量生成失败
        Fallback 行为：直接返回 list_templates() 的全量结果，
        每条记录补充 _distance=0.5（中性距离，不影响后续精排中规则分的权重）。
        """
        query_vec = self._get_embedding(user_input)
        table = self._open_table()

        if query_vec is None or table is None:
            logger.info(
                "TemplateRetriever fallback 到全量加载",
                extra={"reason": "no_vector" if query_vec is None else "no_table"},
            )
            return self._fallback(system_short)

        recalled = self._ann_search(table, query_vec, system_short, top_k)
        if not recalled:
            return self._fallback(system_short)

        return recalled

    def _fallback(self, system_short: str | None) -> list[dict[str, Any]]:
        """Fallback：全量加载已发布模板，补充中性 _distance。"""
        templates = self._template_service.list_templates(system_short)
        return [
            {"template_id": t["id"], "_distance": 0.5}
            for t in templates
        ]
