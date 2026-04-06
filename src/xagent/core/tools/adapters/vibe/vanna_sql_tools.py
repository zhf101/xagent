"""Vanna SQL 资产工具适配层。

Expose Vanna SQL assets to standard task agents as two-stage tools:
- query_vanna_sql_asset
- execute_vanna_sql_asset
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from ....vanna import (
    AskService,
    QueryService,
    SqlAssetExecutionService,
    SqlAssetInferenceService,
)
from ....vanna.contracts import QueryResult
from ....vanna.sql_assets.service import SqlAssetService
from .....web.models.user import User
from .base import ToolCategory
from .factory import register_tool
from .function import FunctionTool

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


class VannaSqlFunctionTool(FunctionTool):
    """FunctionTool subclass for Vanna SQL asset runtime tools."""

    category = ToolCategory.DATABASE


def _coerce_task_id(raw_task_id: Any) -> int | None:
    if raw_task_id is None:
        return None
    if isinstance(raw_task_id, int):
        return raw_task_id
    matched = re.search(r"(\d+)$", str(raw_task_id))
    if matched is None:
        return None
    return int(matched.group(1))


def _resolve_owner_user_name(db: Any, user_id: int) -> str | None:
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        return None
    username = getattr(user, "username", None)
    return str(username) if username is not None else None


def _serialize_query_result(
    result: QueryResult,
    *,
    asset: Any | None = None,
    version: Any | None = None,
) -> dict[str, Any]:
    payload = asdict(result)
    if asset is not None:
        payload["asset"] = asset.to_dict()
    if version is not None:
        payload["version"] = version.to_dict()
    return payload


@register_tool
async def create_vanna_sql_runtime_tools(config: "WebToolConfig") -> list[Any]:
    """Create Vanna SQL asset query/execute tools for authenticated web tasks."""

    try:
        if not hasattr(config, "get_db") or not hasattr(config, "get_user_id"):
            return []

        db = config.get_db()
        user_id = config.get_user_id()
        if not user_id:
            return []

        owner_user_name = _resolve_owner_user_name(db, int(user_id))
        task_id = _coerce_task_id(
            config.get_task_id() if hasattr(config, "get_task_id") else None
        )
        explicit_llm = config.get_llm() if hasattr(config, "get_llm") else None
        task_llm_resolver = (
            (lambda _owner_user_id: explicit_llm) if explicit_llm is not None else None
        )
        query_service = QueryService(
            db,
            ask_service=(
                AskService(db, llm_resolver=task_llm_resolver)
                if task_llm_resolver is not None
                else None
            ),
            inference_service=(
                SqlAssetInferenceService(llm_resolver=task_llm_resolver)
                if task_llm_resolver is not None
                else None
            ),
        )

        async def query_vanna_sql_asset(
            user_query: str,
            datasource_id: int,
            kb_id: int | None = None,
            explicit_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            result = await query_service.query(
                datasource_id=int(datasource_id),
                owner_user_id=int(user_id),
                create_user_name=owner_user_name,
                question=user_query,
                kb_id=kb_id,
                task_id=task_id,
                explicit_params=dict(explicit_params or {}),
                context={},
                auto_run=False,
                auto_infer=True,
            )

            asset = None
            version = None
            if result.asset_id is not None:
                service = SqlAssetService(db)
                asset = service.get_asset(
                    asset_id=int(result.asset_id),
                    owner_user_id=int(user_id),
                )
                version = service.get_effective_version(
                    asset_id=int(asset.id),
                    owner_user_id=int(user_id),
                    version_id=(
                        int(result.asset_version_id)
                        if result.asset_version_id is not None
                        else None
                    ),
                )
            return _serialize_query_result(result, asset=asset, version=version)

        async def execute_vanna_sql_asset(
            question: str,
            asset_id: int | None = None,
            asset_code: str | None = None,
            datasource_id: int | None = None,
            kb_id: int | None = None,
            version_id: int | None = None,
            explicit_params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if asset_id is None and not (asset_code or "").strip():
                raise ValueError("asset_id 与 asset_code 至少提供一个")

            service = SqlAssetService(db)
            if asset_id is not None:
                asset = service.get_asset(
                    asset_id=int(asset_id),
                    owner_user_id=int(user_id),
                )
            else:
                asset = service.get_asset_by_code(
                    asset_code=str(asset_code),
                    owner_user_id=int(user_id),
                )
            version = service.get_effective_version(
                asset_id=int(asset.id),
                owner_user_id=int(user_id),
                version_id=int(version_id) if version_id is not None else None,
            )

            normalized_context: dict[str, Any] = {}
            inference = await query_service.inference_service.infer_bindings(
                asset=asset,
                version=version,
                owner_user_id=int(user_id),
                question=question,
                context=normalized_context,
            )

            run = await SqlAssetExecutionService(db).execute(
                asset=asset,
                version=version,
                datasource_id=(
                    int(datasource_id) if datasource_id is not None else int(asset.datasource_id)
                ),
                kb_id=int(kb_id) if kb_id is not None else int(asset.kb_id),
                owner_user_id=int(user_id),
                owner_user_name=owner_user_name,
                question=question,
                explicit_params=dict(explicit_params or {}),
                context=normalized_context,
                inferred_params=dict((inference or {}).get("bindings") or {}),
                inference_assumptions=list((inference or {}).get("assumptions") or []),
                task_id=task_id,
            )

            binding_plan = dict(run.binding_plan_json or {})
            result = QueryResult(
                mode="asset",
                route="asset_execute",
                execution_status=str(run.execution_status),
                asset_id=int(asset.id),
                asset_version_id=int(version.id),
                asset_run_id=int(run.id),
                asset_code=str(asset.asset_code),
                compiled_sql=str(run.compiled_sql),
                bound_params=dict(run.bound_params_json or {}),
                assumptions=list(binding_plan.get("assumptions") or []),
                execution_result=dict(run.execution_result_json or {}),
                llm_inference=inference,
            )
            return _serialize_query_result(result, asset=asset, version=version)

        return [
            VannaSqlFunctionTool(
                query_vanna_sql_asset,
                name="query_vanna_sql_asset",
                description=(
                    "Search Vanna SQL assets by natural language question. Returns the "
                    "best matched SQL asset, parameter binding preview, missing parameters, "
                    "compiled SQL preview, or ask-fallback result when no asset matches."
                ),
                tags=["sql", "asset", "vanna", "query", "database"],
            ),
            VannaSqlFunctionTool(
                execute_vanna_sql_asset,
                name="execute_vanna_sql_asset",
                description=(
                    "Execute a specific Vanna SQL asset by asset_id or asset_code. "
                    "Execution uses the configured datasource adapter chain for the "
                    "target database and returns the persisted asset run result."
                ),
                tags=["sql", "asset", "vanna", "execute", "database"],
            ),
        ]
    except Exception as exc:
        logger.warning("Failed to create Vanna SQL runtime tools: %s", exc)
        return []
