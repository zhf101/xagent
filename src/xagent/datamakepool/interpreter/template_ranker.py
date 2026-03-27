"""模板精排器。

对 ANN 粗召回的候选集做多路信号融合打分，输出 top-N。

打分公式：
  final = vec_score * 0.55 + sys_score * 0.35 + popularity_score * 0.10

- vec_score：向量余弦相似度，来自 ANN 返回的 _distance（cosine distance → similarity）
- sys_score：system_short 精确匹配或 applicable_systems 包含时给分
- popularity_score：来自 template_stats.used_count，100 次命中以上满分

设计原则：
- 无 DB 依赖时退化为纯向量 + 规则打分（popularity_score 置 0）
- 不依赖 LLM，全部确定性计算，可解释、可调参
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TemplateRanker:
    """多路信号融合精排器。"""

    def __init__(self, db: Session | None = None):
        """
        Args:
            db: SQLAlchemy Session，用于查询 template_stats.used_count。
                不传时跳过热度信号，不影响主流程。
        """
        self._db = db

    def _load_usage_counts(self, template_ids: list[int]) -> dict[int, int]:
        """批量查询 template_stats.used_count，一次 IN 查询。"""
        if not self._db or not template_ids:
            return {}
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(self._db.bind)
            if "template_stats" not in inspector.get_table_names():
                return {}
            placeholders = ", ".join(f"'{tid}'" for tid in template_ids)
            rows = self._db.execute(
                text(
                    f"""
                    SELECT template_id, used_count
                    FROM template_stats
                    WHERE template_id IN ({placeholders})
                    """
                )
            ).mappings()
            return {int(row["template_id"]): int(row["used_count"] or 0) for row in rows}
        except Exception:
            logger.warning("热度数据加载失败，跳过热度信号", exc_info=True)
            return {}

    def _score(
        self,
        candidate: dict[str, Any],
        params: dict[str, Any],
        usage_counts: dict[int, int],
    ) -> tuple[float, dict[str, float]]:
        """对单个候选模板计算融合分和分项拆解。"""
        # 1. 向量相似度分（cosine distance 越小越相似）
        distance = float(candidate.get("_distance", 1.0))
        vec_score = max(0.0, 1.0 - distance)

        # 2. system_short 业务域对齐分
        system_short = (params.get("system_short") or "").lower()
        candidate_system = (candidate.get("system_short") or "").lower()
        applicable = [
            str(s).lower() for s in (candidate.get("applicable_systems") or [])
        ]
        if system_short and candidate_system == system_short:
            sys_score = 1.0
        elif system_short and system_short in applicable:
            sys_score = 0.6
        else:
            sys_score = 0.0

        # 3. 热度分（used_count 归一化，100 次以上满分）
        tid = int(candidate.get("id", 0))
        used = usage_counts.get(tid, 0)
        popularity_score = min(1.0, used / 100.0)

        final_score = vec_score * 0.55 + sys_score * 0.35 + popularity_score * 0.10
        return final_score, {
            "ann_score": round(vec_score, 4),
            "domain_score": round(sys_score, 4),
            "popularity_score": round(popularity_score, 4),
            "final_score": round(final_score, 4),
        }

    def rank(
        self,
        user_input: str,
        params: dict[str, Any],
        candidates: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """对候选集打分并返回 top-N。

        Args:
            user_input: 原始用户输入（当前精排未直接使用，预留给后续 rerank 扩展）。
            params: extract_parameters() 输出的参数字典，含 system_short 等字段。
            candidates: 含 _distance 字段的模板详情列表（来自 batch_get + ANN 距离注入）。
            top_n: 返回的最大候选数量。

        Returns:
            按融合分从高到低排序的 top-N 候选列表。
        """
        if not candidates:
            return []

        template_ids = [int(c.get("id", 0)) for c in candidates if c.get("id")]
        usage_counts = self._load_usage_counts(template_ids)

        scored: list[tuple[float, dict[str, float], dict[str, Any]]] = []
        for candidate in candidates:
            final_score, breakdown = self._score(candidate, params, usage_counts)
            scored.append((final_score, breakdown, candidate))

        scored.sort(key=lambda x: x[0], reverse=True)
        ranked: list[dict[str, Any]] = []
        for _, breakdown, candidate in scored[:top_n]:
            enriched = dict(candidate)
            enriched["score_breakdown"] = breakdown
            ranked.append(enriched)
        return ranked
