"""统一召回漏斗的领域适配器。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from xagent.datamakepool.templates.service import TemplateService

from .protocol import RecallCandidate, RecallQuery


class TemplateRecallAdapter:
    def __init__(
        self,
        *,
        matcher: Any,
        template_service: TemplateService,
        retriever: Any | None = None,
        ranker: Any | None = None,
        rule_candidates: list[dict[str, Any]] | None = None,
    ):
        self._matcher = matcher
        self._template_service = template_service
        self._retriever = retriever
        self._ranker = ranker
        self._rule_candidates = rule_candidates or []

    def coarse_ann(self, query: RecallQuery) -> list[RecallCandidate[dict[str, Any]]]:
        if self._retriever is None:
            return []
        recalled = self._retriever.recall(query.query_text, query.system_short, top_k=max(query.top_k, 50))
        return [
            RecallCandidate(
                candidate_id=f"template:{item['template_id']}",
                payload={"id": int(item["template_id"]), "_distance": float(item.get("_distance", 0.5))},
                ann_score=max(0.0, 1.0 - float(item.get("_distance", 1.0))),
                metadata={"_distance": float(item.get("_distance", 0.5))},
            )
            for item in recalled
        ]

    def coarse_rule(self, query: RecallQuery) -> list[RecallCandidate[dict[str, Any]]]:
        candidates = self._rule_candidates or self._template_service.list_templates(query.system_short)
        return [
            RecallCandidate(candidate_id=f"template:{int(item['id'])}", payload=dict(item))
            for item in candidates
        ]

    def fallback_candidates(self, query: RecallQuery) -> list[RecallCandidate[dict[str, Any]]]:
        return [
            RecallCandidate(
                candidate_id=f"template:{int(item['id'])}",
                payload={**dict(item), "_distance": 0.5},
                metadata={"_distance": 0.5},
            )
            for item in self._template_service.list_templates(query.system_short)
        ]

    def merge_candidates(
        self,
        query: RecallQuery,
        ann_candidates: list[RecallCandidate[dict[str, Any]]],
        rule_candidates: list[RecallCandidate[dict[str, Any]]],
        fallback_candidates: list[RecallCandidate[dict[str, Any]]],
    ) -> list[RecallCandidate[dict[str, Any]]]:
        ann_map = {int(item.payload["id"]): item for item in ann_candidates if item.payload.get("id")}
        merged_ids = set(ann_map.keys())
        merged_ids.update(int(item.payload["id"]) for item in rule_candidates if item.payload.get("id"))
        if not merged_ids:
            merged_ids.update(int(item.payload["id"]) for item in fallback_candidates if item.payload.get("id"))

        details = self._template_service.batch_get(sorted(merged_ids))
        candidates: list[RecallCandidate[dict[str, Any]]] = []
        for detail in details:
            ann_candidate = ann_map.get(int(detail["id"]))
            distance = ann_candidate.metadata.get("_distance", 0.5) if ann_candidate else 0.5
            payload = {**detail, "_distance": distance}
            candidates.append(
                RecallCandidate(
                    candidate_id=f"template:{int(detail['id'])}",
                    payload=payload,
                    ann_score=ann_candidate.ann_score if ann_candidate else None,
                    metadata={"_distance": distance},
                )
            )
        return candidates

    def rerank(
        self,
        query: RecallQuery,
        candidates: list[RecallCandidate[dict[str, Any]]],
    ) -> list[RecallCandidate[dict[str, Any]]]:
        if not candidates:
            return []
        if self._ranker is None:
            return candidates
        ranked = self._ranker.rank(
            query.query_text,
            query.context,
            [item.payload for item in candidates],
            top_n=min(len(candidates), 5),
        )
        score_map = {int(item.get("id", 0)): float(index) for index, item in enumerate(ranked, start=1)}
        candidate_map = {int(item.payload["id"]): item for item in candidates}
        ordered: list[RecallCandidate[dict[str, Any]]] = []
        for item in ranked:
            cid = int(item["id"])
            candidate = candidate_map[cid]
            candidate.payload = item
            candidate.final_score = 1.0 / score_map[cid]
            candidate.score_breakdown = item.get("score_breakdown", {})
            ordered.append(candidate)
        return ordered

    def finalize(
        self,
        query: RecallQuery,
        candidates: list[RecallCandidate[dict[str, Any]]],
    ) -> Any:
        return self._matcher.match(
            query.query_text,
            query.context,
            [item.payload for item in candidates],
        )


class SqlAssetRecallAdapter:
    def __init__(self, *, repository: Any, retriever: Any | None = None):
        # repository 只要求具备当前 SQL 资产 resolver 所需的方法，不强绑定具体类，避免循环导入。
        self._repository = repository
        self._retriever = retriever
        self._active_cache: dict[str, list[Any]] = {}

    def _get_active_assets(self, system_short: str | None) -> list[Any]:
        cache_key = str(system_short or "")
        if cache_key not in self._active_cache:
            self._active_cache[cache_key] = self._repository.list_active_sql_assets(system_short=system_short)
        return self._active_cache[cache_key]

    def coarse_ann(self, query: RecallQuery) -> list[RecallCandidate[Any]]:
        if self._retriever is None:
            return []
        recalled = self._retriever.recall(query.query_text, query.system_short, top_k=max(query.top_k, 20))
        return [
            RecallCandidate(
                candidate_id=f"sql:{int(item['asset_id'])}",
                payload=int(item["asset_id"]),
                ann_score=max(0.0, 1.0 - float(item.get("_distance", 1.0))),
                metadata={"_distance": float(item.get("_distance", 0.5))},
            )
            for item in recalled
        ]

    def coarse_rule(self, query: RecallQuery) -> list[RecallCandidate[Any]]:
        task_lower = query.query_text.lower()
        assets = self._get_active_assets(query.system_short)
        candidates: list[RecallCandidate[Any]] = []
        for asset in assets:
            config = asset.config or {}
            tags = [str(t).lower() for t in (config.get("tags") or [])]
            tables = [str(t).lower() for t in (config.get("table_names") or [])]
            sql_kind = str(config.get("sql_kind") or "").lower()
            if (
                any(tag and tag in task_lower for tag in tags)
                or any(table and table in task_lower for table in tables)
                or (asset.name and asset.name.lower() in task_lower)
                or (sql_kind and sql_kind in task_lower)
            ):
                candidates.append(
                    RecallCandidate(candidate_id=f"sql:{int(asset.id)}", payload=asset)
                )
        return candidates

    def fallback_candidates(self, query: RecallQuery) -> list[RecallCandidate[Any]]:
        fallback_ids = self._repository.list_popular_active_sql_asset_ids(
            system_short=query.system_short,
            limit=5,
        )
        assets = self._get_active_assets(query.system_short)
        return [
            RecallCandidate(candidate_id=f"sql:{asset.id}", payload=asset)
            for asset in assets
            if int(asset.id) in fallback_ids
        ]

    def merge_candidates(self, query: RecallQuery, ann_candidates, rule_candidates, fallback_candidates):
        ann_map = {int(c.payload): c for c in ann_candidates}
        merged_ids = set(ann_map.keys())
        merged_ids.update(int(c.payload.id) for c in rule_candidates)
        merged_ids.update(int(c.payload.id) for c in fallback_candidates)
        assets = self._get_active_assets(query.system_short)
        return [
            RecallCandidate(
                candidate_id=f"sql:{asset.id}",
                payload=asset,
                ann_score=ann_map.get(int(asset.id)).ann_score if int(asset.id) in ann_map else None,
                metadata=ann_map.get(int(asset.id)).metadata if int(asset.id) in ann_map else {"_distance": 0.5},
            )
            for asset in assets
            if int(asset.id) in merged_ids
        ]

    def rerank(self, query: RecallQuery, candidates):
        task_lower = query.query_text.lower()
        reranked: list[RecallCandidate[Any]] = []
        for candidate in candidates:
            asset = candidate.payload
            config = asset.config or {}
            tags = [str(t).lower() for t in (config.get("tags") or [])]
            table_names = [str(t).lower() for t in (config.get("table_names") or [])]
            sql_kind = str(config.get("sql_kind") or "").lower()
            name_lower = asset.name.lower() if asset.name else ""
            desc_lower = (asset.description or "").lower()
            score = 0.0
            matched_signals: list[str] = []
            if candidate.ann_score is not None:
                ann_component = candidate.ann_score * 0.25
                score += ann_component
                matched_signals.append("ann")
            else:
                ann_component = 0.0
            if any(tag and tag in task_lower for tag in tags):
                tag_component = 0.45
                score += tag_component
                matched_signals.append("tags")
            else:
                tag_component = 0.0
            if any(table and table in task_lower for table in table_names):
                table_component = 0.25
                score += table_component
                matched_signals.append("table_names")
            else:
                table_component = 0.0
            if name_lower and name_lower in task_lower:
                name_component = 0.2
                score += name_component
                matched_signals.append("asset_name")
            else:
                name_component = 0.0
            if sql_kind and sql_kind in task_lower:
                kind_component = 0.15
                score += kind_component
                matched_signals.append("sql_kind")
            else:
                kind_component = 0.0
            if desc_lower and any(word in task_lower for word in desc_lower.split() if len(word) > 3):
                desc_component = 0.08
                score += desc_component
                matched_signals.append("description")
            else:
                desc_component = 0.0
            candidate.final_score = round(score, 4)
            candidate.matched_signals = matched_signals
            candidate.score_breakdown = {
                "ann_score": round(ann_component, 4),
                "tag_score": round(tag_component, 4),
                "table_score": round(table_component, 4),
                "name_score": round(name_component, 4),
                "sql_kind_score": round(kind_component, 4),
                "description_score": round(desc_component, 4),
                "final_score": round(score, 4),
            }
            reranked.append(candidate)
        reranked.sort(key=lambda item: item.final_score, reverse=True)
        return reranked

    def finalize(self, query: RecallQuery, candidates) -> dict[str, Any]:
        top_candidates = [
            {
                "asset_id": int(item.payload.id),
                "asset_name": item.payload.name,
                "score": item.final_score,
                "matched_signals": item.matched_signals,
                "score_breakdown": item.score_breakdown,
            }
            for item in candidates[:3]
        ]
        if candidates and candidates[0].final_score >= 0.2:
            best = candidates[0]
            return {
                "matched": True,
                "asset_id": int(best.payload.id),
                "asset_name": best.payload.name,
                "config": best.payload.config or {},
                "reason": f"matched active SQL asset '{best.payload.name}' with score={best.final_score:.2f}",
                "score": best.final_score,
                "matched_signals": best.matched_signals,
                "candidate_count": len(candidates),
                "top_candidates": top_candidates,
            }
        return {
            "matched": False,
            "reason": "no active SQL asset matched",
            "score": candidates[0].final_score if candidates else 0.0,
            "candidate_count": len(candidates),
            "top_candidates": top_candidates,
        }


class HttpAssetRecallAdapter:
    def __init__(self, *, repository: Any, retriever: Any | None = None):
        # repository 只要求具备当前 HTTP 资产 resolver 所需的方法，不强绑定具体类，避免循环导入。
        self._repository = repository
        self._retriever = retriever
        self._active_cache: dict[str, list[Any]] = {}

    def _get_active_assets(self, system_short: str | None) -> list[Any]:
        cache_key = str(system_short or "")
        if cache_key not in self._active_cache:
            self._active_cache[cache_key] = self._repository.list_active_http_assets(system_short=system_short)
        return self._active_cache[cache_key]

    def coarse_ann(self, query: RecallQuery):
        if self._retriever is None:
            return []
        recalled = self._retriever.recall(query.query_text, query.system_short, top_k=max(query.top_k, 20))
        return [
            RecallCandidate(
                candidate_id=f"http:{int(item['asset_id'])}",
                payload=int(item["asset_id"]),
                ann_score=max(0.0, 1.0 - float(item.get("_distance", 1.0))),
                metadata={"_distance": float(item.get("_distance", 0.5))},
            )
            for item in recalled
        ]

    def coarse_rule(self, query: RecallQuery):
        method = str(query.context.get("method") or "").upper()
        return [
            RecallCandidate(candidate_id=f"http:{asset_id}", payload=asset_id)
            for asset_id in self._repository.list_active_http_asset_ids_by_method(method, system_short=query.system_short)
        ]

    def fallback_candidates(self, query: RecallQuery):
        return [
            RecallCandidate(candidate_id=f"http:{asset.id}", payload=int(asset.id))
            for asset in self._get_active_assets(query.system_short)[:5]
        ]

    def merge_candidates(self, query: RecallQuery, ann_candidates, rule_candidates, fallback_candidates):
        ann_map = {int(c.payload): c for c in ann_candidates}
        merged_ids = set(ann_map.keys())
        merged_ids.update(int(c.payload) for c in rule_candidates)
        merged_ids.update(int(c.payload) for c in fallback_candidates)
        assets = self._get_active_assets(query.system_short)
        return [
            RecallCandidate(
                candidate_id=f"http:{asset.id}",
                payload=asset,
                ann_score=ann_map.get(int(asset.id)).ann_score if int(asset.id) in ann_map else None,
                metadata=ann_map.get(int(asset.id)).metadata if int(asset.id) in ann_map else {"_distance": 0.5},
            )
            for asset in assets
            if int(asset.id) in merged_ids
        ]

    def rerank(self, query: RecallQuery, candidates):
        request_path = urlparse(str(query.context.get("url") or "")).path.rstrip("/") or "/"
        request_method = str(query.context.get("method") or "").upper()
        reranked: list[RecallCandidate[Any]] = []
        request_tokens = set(t for t in re.split(r"[/_\-?=&.]+", request_path.lower()) if len(t) > 1)
        for candidate in candidates:
            asset = candidate.payload
            config = asset.config or {}
            asset_method = str(config.get("method") or "").upper()
            base_url = str(config.get("base_url") or "").rstrip("/")
            path_template = str(config.get("path_template") or "").rstrip("/") or "/"
            expected_path = urlparse(f"{base_url}{path_template}").path.rstrip("/") or "/"
            score = 0.0
            matched_signals: list[str] = []
            if candidate.ann_score is not None:
                ann_component = candidate.ann_score * 0.2
                score += ann_component
                matched_signals.append("ann")
            else:
                ann_component = 0.0
            if asset_method and asset_method == request_method:
                method_component = 0.4
                score += method_component
                matched_signals.append("method")
            else:
                method_component = 0.0
            if expected_path == request_path:
                path_component = 1.0
                score += path_component
                matched_signals.append("path_exact")
            else:
                path_lower = path_template.lower()
                asset_name_lower = (asset.name or "").lower()
                asset_desc_lower = (asset.description or "").lower()
                token_score = sum(1 for token in request_tokens if token in path_lower or token in asset_name_lower or token in asset_desc_lower)
                if token_score:
                    path_component = min(token_score * 0.08, 0.32)
                    score += path_component
                    matched_signals.append("path_tokens")
                else:
                    path_component = 0.0
            candidate.final_score = round(score, 4)
            candidate.matched_signals = matched_signals
            candidate.score_breakdown = {
                "ann_score": round(ann_component, 4),
                "method_score": round(method_component, 4),
                "path_score": round(path_component, 4),
                "final_score": round(score, 4),
            }
            reranked.append(candidate)
        reranked.sort(key=lambda item: item.final_score, reverse=True)
        return reranked

    def finalize(self, query: RecallQuery, candidates) -> dict[str, Any]:
        request_path = urlparse(str(query.context.get("url") or "")).path.rstrip("/") or "/"
        request_method = str(query.context.get("method") or "").upper()
        for candidate in candidates:
            asset = candidate.payload
            config = asset.config or {}
            asset_method = str(config.get("method") or "").upper()
            base_url = str(config.get("base_url") or "").rstrip("/")
            path_template = str(config.get("path_template") or "").rstrip("/") or "/"
            expected_path = urlparse(f"{base_url}{path_template}").path.rstrip("/") or "/"
            if expected_path == request_path and (not asset_method or asset_method == request_method):
                return {
                    "matched": True,
                    "asset_id": asset.id,
                    "asset_name": asset.name,
                    "config": config,
                    "reason": f"matched active HTTP asset '{asset.name}'",
                }

        fallback_candidates = [
            {
                "asset_id": int(item.payload.id),
                "asset_name": item.payload.name,
                "description": item.payload.description,
                "path_template": (item.payload.config or {}).get("path_template"),
                "method": (item.payload.config or {}).get("method"),
                "match_score": item.final_score,
                "score_breakdown": item.score_breakdown,
            }
            for item in candidates[:3]
            if item.final_score > 0
        ]
        return {
            "matched": False,
            "reason": "no active HTTP asset matched by exact path; see fallback_candidates",
            "fallback_candidates": fallback_candidates,
        }


class LegacyScenarioRecallAdapter:
    def __init__(
        self,
        *,
        catalog: list[Any],
        retriever: Any | None = None,
    ):
        self._catalog = catalog
        self._retriever = retriever

    def coarse_ann(self, query: RecallQuery):
        if self._retriever is None:
            return []
        recalled = self._retriever.recall(
            query=query.query_text,
            top_k=max(query.top_k * 4, 20),
            fallback_entries=[entry.to_dict() for entry in self._catalog],
        )
        return [
            RecallCandidate(
                candidate_id=f"scenario:{item['scenario_id']}",
                payload=str(item["scenario_id"]),
                ann_score=max(0.0, 1.0 - float(item.get("_distance", 1.0))),
                metadata={"_distance": float(item.get("_distance", 0.5))},
            )
            for item in recalled
        ]

    def coarse_rule(self, query: RecallQuery):
        query_lower = query.query_text.lower()
        candidates: list[RecallCandidate[Any]] = []
        for entry in self._catalog:
            score = 0.0
            if query.system_short and entry.system_short and entry.system_short.lower() == query.system_short.lower():
                score += 0.45
            if entry.system_short and entry.system_short.lower() in query_lower:
                score += 0.25
            if entry.scenario_name.lower() in query_lower:
                score += 0.35
            for tag in entry.business_tags:
                if str(tag).lower() in query_lower:
                    score += 0.18
            for tag in entry.entity_tags:
                if str(tag).lower() in query_lower:
                    score += 0.12
            if score > 0:
                candidates.append(
                    RecallCandidate(
                        candidate_id=f"scenario:{entry.scenario_id}",
                        payload=entry,
                        rule_score=round(score, 4),
                    )
                )
        return candidates

    def fallback_candidates(self, query: RecallQuery):
        fallback = sorted(self._catalog, key=lambda e: e.usage_count, reverse=True)[:5]
        return [
            RecallCandidate(candidate_id=f"scenario:{entry.scenario_id}", payload=entry)
            for entry in fallback
        ]

    def merge_candidates(self, query: RecallQuery, ann_candidates, rule_candidates, fallback_candidates):
        ann_map = {str(c.payload): c for c in ann_candidates}
        rule_map = {str(c.payload.scenario_id): c for c in rule_candidates}
        merged_ids = set(ann_map.keys()) | set(rule_map.keys()) | {
            str(c.payload.scenario_id) for c in fallback_candidates
        }
        candidates: list[RecallCandidate[Any]] = []
        for entry in self._catalog:
            if entry.scenario_id not in merged_ids:
                continue
            ann_candidate = ann_map.get(entry.scenario_id)
            rule_candidate = rule_map.get(entry.scenario_id)
            candidates.append(
                RecallCandidate(
                    candidate_id=f"scenario:{entry.scenario_id}",
                    payload=entry,
                    ann_score=ann_candidate.ann_score if ann_candidate else None,
                    rule_score=rule_candidate.rule_score if rule_candidate else None,
                    metadata=ann_candidate.metadata if ann_candidate else {"_distance": 0.5},
                )
            )
        return candidates

    def rerank(self, query: RecallQuery, candidates):
        query_lower = query.query_text.lower()
        reranked: list[RecallCandidate[Any]] = []
        for candidate in candidates:
            entry = candidate.payload
            score = candidate.rule_score or 0.0
            matched_signals: list[str] = []
            if candidate.ann_score is not None:
                ann_component = candidate.ann_score * 0.25
                score += ann_component
                matched_signals.append("ann")
            else:
                ann_component = 0.0
            if query.system_short and entry.system_short and entry.system_short.lower() == query.system_short.lower():
                matched_signals.append("system_short")
                system_component = 0.45
            else:
                system_component = 0.0
            name_component = 0.0
            desc_component = 0.0
            for token in re.split(r"\s+|，|,|；|;", query_lower):
                if not token:
                    continue
                if token in entry.scenario_name.lower():
                    name_component += 0.12
                    score += 0.12
                    matched_signals.append("scenario_name")
                if token in entry.description.lower():
                    desc_component += 0.08
                    score += 0.08
                    matched_signals.append("description")
            popularity_component = min((entry.usage_count or 0) * 0.015, 0.2)
            success_component = min((entry.success_rate or 0) / 1000.0, 0.1)
            score += popularity_component
            score += success_component
            candidate.final_score = round(score, 4)
            candidate.matched_signals = sorted(set(matched_signals))
            candidate.score_breakdown = {
                "ann_score": round(ann_component, 4),
                "domain_score": round(system_component, 4),
                "name_score": round(name_component, 4),
                "description_score": round(desc_component, 4),
                "popularity_score": round(popularity_component, 4),
                "success_score": round(success_component, 4),
                "final_score": round(score, 4),
            }
            reranked.append(candidate)
        reranked.sort(key=lambda item: item.final_score, reverse=True)
        return reranked

    def finalize(self, query: RecallQuery, candidates):
        results = [
            {
                **candidate.payload.to_dict(),
                "match_score": candidate.final_score,
                "matched_signals": candidate.matched_signals,
                "score_breakdown": candidate.score_breakdown,
            }
            for candidate in candidates[: max(1, min(query.top_k, 10))]
            if candidate.final_score > 0
        ]
        if results:
            return results
        fallback = sorted(self._catalog, key=lambda e: e.usage_count, reverse=True)
        return [
            {
                **entry.to_dict(),
                "match_score": 0.0,
                "recall_strategy": "fallback_by_popularity",
            }
            for entry in fallback[: max(1, min(query.top_k, 10))]
        ]
