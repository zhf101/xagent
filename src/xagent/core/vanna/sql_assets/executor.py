"""SQL Asset 执行服务。"""

from __future__ import annotations

import inspect

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ....core.database.adapters import create_adapter_for_type
from ....core.database.config import (
    database_connection_config_from_url,
    normalize_database_name,
    resolve_database_name_from_url,
)
from ....web.models.text2sql import Text2SQLDatabase
from ....web.models.vanna import (
    VannaSqlAsset,
    VannaSqlAssetRun,
    VannaSqlAssetRunStatus,
    VannaSqlAssetVersion,
)
from .binding import SqlAssetBindingService
from .compiler import SqlTemplateCompiler


class SqlAssetExecutionService:
    """执行 SQL Asset，并写入运行事实。"""

    def __init__(
        self,
        db: Session,
        *,
        binding_service: SqlAssetBindingService | None = None,
        compiler: SqlTemplateCompiler | None = None,
        sql_executor=None,
    ) -> None:
        self.db = db
        self.binding_service = binding_service or SqlAssetBindingService()
        self.compiler = compiler or SqlTemplateCompiler()
        self.sql_executor = sql_executor

    def _resolve_asset_database_name(self, asset: VannaSqlAsset) -> str | None:
        normalized = normalize_database_name(getattr(asset, "database_name", None))
        if normalized is not None:
            return normalized
        source_datasource = (
            self.db.query(Text2SQLDatabase)
            .filter(Text2SQLDatabase.id == int(asset.datasource_id))
            .first()
        )
        if source_datasource is None:
            return None
        return normalize_database_name(
            getattr(source_datasource, "database_name", None)
        ) or normalize_database_name(resolve_database_name_from_url(str(source_datasource.url)))

    async def execute(
        self,
        *,
        asset: VannaSqlAsset,
        version: VannaSqlAssetVersion,
        datasource_id: int | None = None,
        kb_id: int | None = None,
        owner_user_id: int,
        owner_user_name: str | None,
        question: str,
        explicit_params: dict,
        context: dict,
        inferred_params: dict | None = None,
        inference_assumptions: list[str] | None = None,
        task_id: int | None = None,
    ) -> VannaSqlAssetRun:
        binding = self.binding_service.bind(
            asset=asset,
            version=version,
            question=question,
            explicit_params=explicit_params,
            context=context,
            inferred_params=inferred_params,
            inference_assumptions=inference_assumptions,
        )
        missing_params = list(binding.get("missing_params") or [])
        if missing_params:
            raise ValueError("Missing required parameters: " + ", ".join(missing_params))

        compiled = self.compiler.compile(
            template_sql=str(version.template_sql),
            parameter_schema_json=list(version.parameter_schema_json or []),
            render_config_json=dict(version.render_config_json or {}),
            bound_params=dict(binding.get("bound_params") or {}),
        )
        target_datasource_id = (
            int(datasource_id) if datasource_id is not None else int(asset.datasource_id)
        )
        target_kb_id = int(kb_id) if kb_id is not None else int(asset.kb_id)
        target_datasource = (
            self.db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.id == target_datasource_id,
                Text2SQLDatabase.user_id == int(owner_user_id),
            )
            .first()
        )
        if target_datasource is None:
            raise ValueError(f"Datasource {target_datasource_id} was not found")
        if str(target_datasource.system_short) != str(asset.system_short):
            raise ValueError(
                "Target datasource must belong to the same system as the SQL asset"
            )
        target_database_name = normalize_database_name(
            getattr(target_datasource, "database_name", None)
        ) or normalize_database_name(resolve_database_name_from_url(str(target_datasource.url)))
        asset_database_name = self._resolve_asset_database_name(asset)
        if target_database_name is None:
            raise ValueError(f"Datasource {target_datasource_id} has no database_name")
        if asset_database_name is None:
            raise ValueError(f"SQL asset {asset.id} has no database_name")
        if target_database_name != asset_database_name:
            raise ValueError(
                "Target datasource must belong to the same database as the SQL asset"
            )
        execution_result = await self._execute_compiled_sql(
            datasource_id=target_datasource_id,
            owner_user_id=int(owner_user_id),
            compiled_sql=str(compiled["compiled_sql"]),
            bound_params=dict(compiled["bound_params"]),
            task_id=task_id,
        )

        run = VannaSqlAssetRun(
            asset_id=int(asset.id),
            asset_version_id=int(version.id),
            kb_id=target_kb_id,
            datasource_id=target_datasource_id,
            task_id=task_id,
            question_text=question.strip(),
            resolved_by="asset_search",
            binding_plan_json={
                "params": dict(binding.get("binding_plan") or {}),
                "assumptions": list(binding.get("assumptions") or []),
            },
            bound_params_json=dict(compiled.get("bound_params") or {}),
            compiled_sql=str(compiled["compiled_sql"]),
            execution_status=(
                VannaSqlAssetRunStatus.EXECUTED.value
                if execution_result.get("success")
                else VannaSqlAssetRunStatus.FAILED.value
            ),
            execution_result_json=execution_result,
            approval_status="approved" if execution_result.get("success") else None,
            create_user_id=int(owner_user_id),
            create_user_name=owner_user_name,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    async def _execute_compiled_sql(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        compiled_sql: str,
        bound_params: dict,
        task_id: int | None,
    ) -> dict:
        datasource = (
            self.db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.id == int(datasource_id),
                Text2SQLDatabase.user_id == int(owner_user_id),
            )
            .first()
        )
        if datasource is None:
            raise ValueError(f"Datasource {datasource_id} was not found")

        if self.sql_executor is not None:
            result = self.sql_executor(
                datasource=datasource,
                sql=compiled_sql,
                params=bound_params,
                task_id=task_id,
                user_id=owner_user_id,
            )
            if inspect.isawaitable(result):
                result = await result
            return dict(result or {})

        config = database_connection_config_from_url(
            make_url(datasource.url),
            read_only=datasource.read_only,
        )
        adapter = create_adapter_for_type(datasource.type.value, config)
        await adapter.connect()
        try:
            query_result = await adapter.execute_query(compiled_sql, params=bound_params)
        finally:
            await adapter.disconnect()

        columns = list(query_result.rows[0].keys()) if query_result.rows else []
        return {
            "success": True,
            "rows": query_result.rows,
            "row_count": (
                query_result.affected_rows
                if query_result.affected_rows is not None
                else len(query_result.rows)
            ),
            "columns": columns,
            "message": "SQL asset executed successfully",
            "metadata": query_result.metadata or {},
        }
