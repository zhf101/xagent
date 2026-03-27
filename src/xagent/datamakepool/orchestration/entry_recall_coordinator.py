"""入口统一召回协调层。

放在 TaskModeGateway 之后、template planner / orchestrator 之前。
职责：
- 聚合 template / sql asset / http asset / legacy scenario 四类候选
- 做统一策略选择
- 输出可注入 task_context 的标准结果
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from xagent.datamakepool.assets.repositories import HttpAssetRepository, SqlAssetRepository
from xagent.datamakepool.assets.service import HttpAssetResolverService, SqlAssetResolverService
from xagent.datamakepool.assets.http_asset_retriever import HttpAssetRetriever
from xagent.datamakepool.assets.sql_asset_retriever import SqlAssetRetriever
from xagent.datamakepool.recall_funnel import load_default_embedding_adapter
from xagent.datamakepool.templates import TemplateRetriever, TemplateService
from xagent.datamakepool.interpreter import TemplateRanker
from xagent.datamakepool.tools.legacy_scenario_meta_tools import LegacyScenarioCatalogService
from xagent.web.models.user import User
from xagent.web.tools.config import WebToolConfig

from .datamakepool_execution_planner import DatamakepoolExecutionPlanner
from .entry_recall_models import EntryRecallCandidate, EntryRecallResult


class EntryRecallCoordinator:
    """统一入口召回协调器。"""

    def __init__(self, *, db: Session, user: User):
        self._db = db
        self._user = user
        self._embedding = load_default_embedding_adapter(db, int(user.id))
        self._db_dir = "data/lancedb"

    def _build_template_planner(self) -> DatamakepoolExecutionPlanner:
        template_service = TemplateService(self._db)
        template_retriever = (
            TemplateRetriever(self._db_dir, self._embedding, template_service)
            if self._embedding is not None
            else None
        )
        template_ranker = (
            TemplateRanker(self._db)
            if template_retriever is not None
            else None
        )
        return DatamakepoolExecutionPlanner(
            template_service,
            retriever=template_retriever,
            ranker=template_ranker,
        )

    def _build_sql_candidates(self, query_text: str, system_short: str | None) -> list[EntryRecallCandidate]:
        repo = SqlAssetRepository(self._db)
        retriever = (
            SqlAssetRetriever(self._db_dir, self._embedding, repo)
            if self._embedding is not None
            else None
        )
        result = SqlAssetResolverService(repo, retriever=retriever).resolve(
            task=query_text,
            system_short=system_short,
        )
        candidates = []
        for item in result.top_candidates or []:
            candidates.append(
                EntryRecallCandidate(
                    source_type="sql_asset",
                    candidate_id=f"sql:{item.get('asset_id')}",
                    display_name=str(item.get("asset_name") or "未命名 SQL 资产"),
                    system_short=system_short,
                    score=float(item.get("score") or 0.0),
                    matched_signals=list(item.get("matched_signals") or []),
                    summary=result.reason,
                    payload=item,
                )
            )
        return candidates

    def _build_http_candidates(self, query_text: str, system_short: str | None) -> list[EntryRecallCandidate]:
        repo = HttpAssetRepository(self._db)
        retriever = (
            HttpAssetRetriever(self._db_dir, self._embedding, repo)
            if self._embedding is not None
            else None
        )
        assets = repo.list_active_http_assets(system_short=system_short)
        recalled_ids: set[int] = set()
        if retriever is not None:
            recalled = retriever.recall(query_text, system_short=system_short, top_k=10)
            recalled_ids = {int(item["asset_id"]) for item in recalled}
        query_lower = query_text.lower()
        query_tokens = set(t for t in re.split(r"\\s+|，|,|；|;|/|_|-", query_lower) if len(t) > 1)
        candidates: list[EntryRecallCandidate] = []
        for asset in assets:
            config = asset.config or {}
            path_template = str(config.get("path_template") or "")
            name_lower = (asset.name or "").lower()
            desc_lower = (asset.description or "").lower()
            token_hits = sum(1 for token in query_tokens if token in name_lower or token in desc_lower or token in path_template.lower())
            ann_component = 0.35 if int(asset.id) in recalled_ids else 0.0
            token_component = min(token_hits * 0.12, 0.48)
            final_score = round(ann_component + token_component, 4)
            if final_score <= 0:
                continue
            signals: list[str] = []
            if ann_component:
                signals.append("ann")
            if token_component:
                signals.append("path_or_desc_tokens")
            candidates.append(
                EntryRecallCandidate(
                    source_type="http_asset",
                    candidate_id=f"http:{asset.id}",
                    display_name=asset.name,
                    system_short=asset.system_short,
                    score=final_score,
                    matched_signals=signals,
                    summary=asset.description,
                    payload={
                        "asset_id": asset.id,
                        "asset_name": asset.name,
                        "path_template": path_template,
                        "method": config.get("method"),
                    },
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:5]

    async def _build_legacy_candidates(self, query_text: str, system_short: str | None) -> list[EntryRecallCandidate]:
        tool_config = WebToolConfig(
            db=self._db,
            request=None,
            user_id=int(self._user.id),
            is_admin=bool(self._user.is_admin),
            include_mcp_tools=False,
        )
        service = LegacyScenarioCatalogService(
            mcp_configs=tool_config.get_mcp_server_configs(),
            user_id=int(self._user.id),
            agent_service=None,
            db=self._db,
            db_dir=self._db_dir,
            embedding_model=self._embedding,
        )
        results = await service.search(query_text, system_short, top_k=5)
        candidates: list[EntryRecallCandidate] = []
        for item in results:
            candidates.append(
                EntryRecallCandidate(
                    source_type="legacy_scenario",
                    candidate_id=str(item.get("scenario_id") or ""),
                    display_name=str(item.get("scenario_name") or "未命名场景"),
                    system_short=item.get("system_short"),
                    score=float(item.get("match_score") or 0.0),
                    matched_signals=list(item.get("matched_signals") or []),
                    summary=item.get("description"),
                    payload=item,
                )
            )
        return candidates

    def _build_missing_params(self, selected: EntryRecallCandidate | None) -> list[dict[str, Any]]:
        if selected is None:
            return []
        if selected.source_type == "sql_asset":
            schema = selected.payload.get("config", {}).get("parameter_schema") or {}
            return [
                {"field": key, "label": value or key}
                for key, value in schema.items()
            ]
        if selected.source_type == "legacy_scenario":
            return [
                {"field": field, "label": field}
                for field in selected.payload.get("input_schema_summary", [])[:8]
            ]
        if selected.source_type == "http_asset":
            return []
        return []

    def _select_strategy(
        self,
        template_decision,
        sql_candidates: list[EntryRecallCandidate],
        http_candidates: list[EntryRecallCandidate],
        legacy_candidates: list[EntryRecallCandidate],
    ) -> tuple[str, EntryRecallCandidate | None]:
        if template_decision.execution_path == "template_direct" and template_decision.match_result.matched_template:
            matched = template_decision.match_result.matched_template
            return "template_direct", EntryRecallCandidate(
                source_type="template",
                candidate_id=f"template:{matched.template_id}",
                display_name=matched.template_name,
                system_short=matched.system_short,
                score=float(template_decision.match_result.confidence),
                matched_signals=["template_full_match"],
                payload={
                    "template_id": matched.template_id,
                    "template_name": matched.template_name,
                    "version": matched.version,
                },
            )

        direct_candidates = sorted(
            [*(sql_candidates[:1]), *(http_candidates[:1]), *(legacy_candidates[:1])],
            key=lambda item: item.score,
            reverse=True,
        )
        best_direct = direct_candidates[0] if direct_candidates else None
        if best_direct and best_direct.score >= 0.55:
            mapping = {
                "sql_asset": "sql_asset_direct",
                "http_asset": "http_asset_direct",
                "legacy_scenario": "legacy_direct",
            }
            return mapping[best_direct.source_type], best_direct

        if template_decision.execution_path == "template_augmented":
            return "template_augmented", best_direct

        if best_direct is not None:
            return "orchestrator_augmented", best_direct

        return "orchestrator_full", None

    async def coordinate(self, user_input: str) -> EntryRecallResult:
        planner = self._build_template_planner()
        template_decision = planner.build_decision(user_input)
        params = template_decision.params
        system_short = params.get("system_short")
        sql_candidates = self._build_sql_candidates(user_input, system_short)
        http_candidates = self._build_http_candidates(user_input, system_short)
        legacy_candidates = await self._build_legacy_candidates(user_input, system_short)
        selected_strategy, selected_candidate = self._select_strategy(
            template_decision,
            sql_candidates,
            http_candidates,
            legacy_candidates,
        )
        template_candidates: list[EntryRecallCandidate] = []
        if template_decision.match_result.matched_template:
            matched = template_decision.match_result.matched_template
            template_candidates.append(
                EntryRecallCandidate(
                    source_type="template",
                    candidate_id=f"template:{matched.template_id}",
                    display_name=matched.template_name,
                    system_short=matched.system_short,
                    score=float(template_decision.match_result.confidence),
                    matched_signals=["template_match"],
                    payload={
                        "template_id": matched.template_id,
                        "template_name": matched.template_name,
                        "version": matched.version,
                    },
                )
            )
        return EntryRecallResult(
            selected_strategy=selected_strategy,
            selected_candidate=selected_candidate,
            template_decision=template_decision,
            template_candidates=template_candidates,
            sql_asset_candidates=sql_candidates,
            http_asset_candidates=http_candidates,
            legacy_candidates=legacy_candidates,
            missing_params=self._build_missing_params(selected_candidate),
            debug={
                "query": user_input,
                "template_match_type": template_decision.match_result.match_type,
                "template_recall_strategy": template_decision.match_result.recall_strategy,
            },
        )
