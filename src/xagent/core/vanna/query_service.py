"""统一 asset-first / ask-fallback 编排服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...web.models.vanna import VannaSqlAsset, VannaSqlAssetVersion
from .ask_service import AskService
from .contracts import QueryResult
from .sql_assets import (
    SqlAssetBindingService,
    SqlAssetExecutionService,
    SqlAssetInferenceService,
    SqlAssetResolver,
    SqlAssetService,
    SqlTemplateCompiler,
)


class QueryService:
    """先复用资产，未命中再回退 ask。"""

    DEFAULT_MIN_MATCH_SCORE = 0.55
    DEFAULT_MIN_SCORE_MARGIN = 0.15

    def __init__(
        self,
        db: Session,
        *,
        ask_service: AskService | None = None,
        asset_service: SqlAssetService | None = None,
        resolver: SqlAssetResolver | None = None,
        binding_service: SqlAssetBindingService | None = None,
        compiler: SqlTemplateCompiler | None = None,
        execution_service: SqlAssetExecutionService | None = None,
        inference_service: SqlAssetInferenceService | None = None,
    ) -> None:
        self.db = db
        self.ask_service = ask_service or AskService(db)
        self.asset_service = asset_service or SqlAssetService(db)
        self.resolver = resolver or SqlAssetResolver(db)
        self.binding_service = binding_service or SqlAssetBindingService()
        self.compiler = compiler or SqlTemplateCompiler()
        self.execution_service = execution_service or SqlAssetExecutionService(db)
        self.inference_service = inference_service or SqlAssetInferenceService()

    async def query(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        question: str,
        kb_id: int | None = None,
        task_id: int | None = None,
        explicit_params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        auto_run: bool = False,
        auto_train_on_success: bool = False,
        auto_infer: bool = False,
        top_k_assets: int = 5,
        asset_match_min_score: float | None = None,
        asset_match_min_margin: float | None = None,
        top_k_sql: int | None = None,
        top_k_schema: int | None = None,
        top_k_doc: int | None = None,
    ) -> QueryResult:
        normalized_question = str(question or "").strip()
        explicit_params = dict(explicit_params or {})
        context = dict(context or {})

        matches = self.resolver.resolve(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            question=normalized_question,
            kb_id=kb_id,
            top_k=int(top_k_assets),
        )
        selected = self._select_match(
            matches,
            min_score=(
                float(asset_match_min_score)
                if asset_match_min_score is not None
                else self.DEFAULT_MIN_MATCH_SCORE
            ),
            min_margin=(
                float(asset_match_min_margin)
                if asset_match_min_margin is not None
                else self.DEFAULT_MIN_SCORE_MARGIN
            ),
        )
        if selected is None:
            return await self._fallback_to_ask(
                datasource_id=datasource_id,
                owner_user_id=owner_user_id,
                create_user_name=create_user_name,
                question=normalized_question,
                kb_id=kb_id,
                task_id=task_id,
                auto_run=auto_run,
                auto_train_on_success=auto_train_on_success,
                top_k_sql=top_k_sql,
                top_k_schema=top_k_schema,
                top_k_doc=top_k_doc,
            )

        asset = selected["asset"]
        version = selected["version"]
        inference: dict[str, Any] | None = None
        if auto_infer:
            inference = await self.inference_service.infer_bindings(
                asset=asset,
                version=version,
                owner_user_id=int(owner_user_id),
                question=normalized_question,
                context=context,
            )

        binding = self.binding_service.bind(
            asset=asset,
            version=version,
            question=normalized_question,
            explicit_params=explicit_params,
            context=context,
            inferred_params=dict((inference or {}).get("bindings") or {}),
            inference_assumptions=list((inference or {}).get("assumptions") or []),
        )
        if binding["missing_params"]:
            return QueryResult(
                mode="asset",
                route="asset_missing_params",
                execution_status="missing_params",
                asset_id=int(asset.id),
                asset_version_id=int(version.id),
                asset_code=str(asset.asset_code),
                asset_match_score=float(selected["score"]),
                asset_match_reason=str(selected["reason"]),
                bound_params=dict(binding["bound_params"]),
                missing_params=list(binding["missing_params"]),
                assumptions=list(binding["assumptions"]),
                llm_inference=inference,
            )

        compiled = self.compiler.compile(
            template_sql=str(version.template_sql),
            parameter_schema_json=list(version.parameter_schema_json or []),
            render_config_json=dict(version.render_config_json or {}),
            bound_params=dict(binding["bound_params"]),
        )
        if not auto_run:
            return QueryResult(
                mode="asset",
                route="asset_preview",
                execution_status="bound",
                asset_id=int(asset.id),
                asset_version_id=int(version.id),
                asset_code=str(asset.asset_code),
                asset_match_score=float(selected["score"]),
                asset_match_reason=str(selected["reason"]),
                compiled_sql=str(compiled["compiled_sql"]),
                bound_params=dict(compiled["bound_params"]),
                assumptions=list(binding["assumptions"]),
                llm_inference=inference,
            )

        run = await self.execution_service.execute(
            asset=asset,
            version=version,
            owner_user_id=int(owner_user_id),
            owner_user_name=create_user_name,
            question=normalized_question,
            explicit_params=explicit_params,
            context=context,
            inferred_params=dict((inference or {}).get("bindings") or {}),
            inference_assumptions=list((inference or {}).get("assumptions") or []),
            task_id=task_id,
        )
        binding_plan = dict(run.binding_plan_json or {})
        return QueryResult(
            mode="asset",
            route="asset_execute",
            execution_status=str(run.execution_status),
            asset_id=int(asset.id),
            asset_version_id=int(version.id),
            asset_run_id=int(run.id),
            asset_code=str(asset.asset_code),
            asset_match_score=float(selected["score"]),
            asset_match_reason=str(selected["reason"]),
            compiled_sql=str(run.compiled_sql),
            bound_params=dict(run.bound_params_json or {}),
            assumptions=list(binding_plan.get("assumptions") or []),
            execution_result=dict(run.execution_result_json or {}),
            llm_inference=inference,
        )

    def _select_match(
        self,
        matches: list[dict[str, Any]],
        *,
        min_score: float,
        min_margin: float,
    ) -> dict[str, Any] | None:
        eligible: list[dict[str, Any]] = []
        for item in matches:
            asset = item.get("asset")
            version = item.get("version")
            if not (
                isinstance(asset, VannaSqlAsset)
                and isinstance(version, VannaSqlAssetVersion)
            ):
                continue
            score = float(item.get("score") or 0.0)
            reason_tokens = {
                token.strip()
                for token in str(item.get("reason") or "").split(",")
                if token.strip()
            }
            if score >= float(min_score) or "asset_code_exact" in reason_tokens:
                eligible.append(item)

        if not eligible:
            return None
        if len(eligible) == 1:
            return eligible[0]

        best = eligible[0]
        runner_up = eligible[1]
        best_reasons = {
            token.strip()
            for token in str(best.get("reason") or "").split(",")
            if token.strip()
        }
        if "asset_code_exact" in best_reasons:
            return best

        best_score = float(best.get("score") or 0.0)
        runner_up_score = float(runner_up.get("score") or 0.0)
        if (best_score - runner_up_score) < float(min_margin):
            return None
        return best

    async def _fallback_to_ask(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        question: str,
        kb_id: int | None,
        task_id: int | None,
        auto_run: bool,
        auto_train_on_success: bool,
        top_k_sql: int | None,
        top_k_schema: int | None,
        top_k_doc: int | None,
    ) -> QueryResult:
        ask_result = await self.ask_service.ask(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            create_user_name=create_user_name,
            question=question,
            kb_id=kb_id,
            task_id=task_id,
            top_k_sql=top_k_sql,
            top_k_schema=top_k_schema,
            top_k_doc=top_k_doc,
            auto_run=bool(auto_run),
            auto_train_on_success=bool(auto_train_on_success),
        )
        return QueryResult(
            mode="ask",
            route="ask_fallback",
            execution_status=str(ask_result.execution_status),
            ask_run_id=int(ask_result.ask_run_id),
            generated_sql=ask_result.generated_sql,
            sql_confidence=ask_result.sql_confidence,
            execution_result=dict(ask_result.execution_result or {}),
            auto_train_entry_id=ask_result.auto_train_entry_id,
        )
