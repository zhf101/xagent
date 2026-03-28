"""SQL 模板步骤执行器。"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.engine import make_url

from xagent.core.database.adapters import create_adapter_for_type
from xagent.core.database.config import database_connection_config_from_url
from xagent.datamakepool.interceptors import check_sql_needs_approval

from ..context import TemplateRuntimeContext
from ..models import TemplateRuntimeStep, TemplateStepResult
from .base import TemplateStepExecutor


class SqlTemplateStepExecutor(TemplateStepExecutor):
    """SQL 安全只读执行器。

    这层明确坚持当前治理边界：
    - 只允许治理过的 SQL 资产
    - 只允许只读连接
    - 不允许消费前序步骤结果拼 SQL
    """

    kind = "sql"

    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        self._prepare_sql_plan(step, context)

    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        plan = self._prepare_sql_plan(step, context)
        return replace(
            step,
            input_data={
                "sql": plan["sql"],
                "datasource_asset_id": plan["datasource_asset_id"],
            },
            config=plan,
        )

    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        adapter = None
        try:
            config = database_connection_config_from_url(
                make_url(step.config["db_url"]),
                read_only=True,
            )
            adapter = create_adapter_for_type(step.config["db_type"], config)
            await adapter.connect()
            result = await adapter.execute_query(step.config["sql"])
            payload = {
                "success": True,
                "sql": step.config["sql"],
                "rows": context.json_safe(result.rows),
                "row_count": len(result.rows),
                "affected_rows": result.affected_rows,
                "execution_time_ms": result.execution_time_ms,
                "metadata": context.json_safe(result.metadata or {}),
                "output": f"SQL executed successfully, returned {len(result.rows)} rows.",
                "summary": f"SQL returned {len(result.rows)} rows.",
            }
            return TemplateStepResult(
                success=True,
                output=str(payload["output"]),
                summary=str(payload["summary"]),
                output_data=context.json_safe(payload),
            )
        except Exception as exc:
            payload = {
                "success": False,
                "sql": step.config.get("sql"),
                "error": str(exc),
            }
            return TemplateStepResult(
                success=False,
                output=str(exc),
                summary=None,
                output_data=context.json_safe(payload),
                error_message=str(exc),
            )
        finally:
            if adapter is not None:
                try:
                    await adapter.disconnect()
                except Exception:
                    pass

    def _prepare_sql_plan(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> dict[str, object]:
        asset_snapshot = step.asset_snapshot or {}
        if asset_snapshot.get("asset_type") != "sql":
            raise ValueError("sql_step_requires_governed_sql_asset")

        sql_template = str(
            step.raw_step.get("sql")
            or step.raw_step.get("sql_template")
            or (asset_snapshot.get("config") or {}).get("sql_template")
            or ""
        ).strip()
        sql = context.render_value(
            sql_template,
            allow_step_refs=False,
            strict_steps=False,
        )
        sql = str(sql).strip()
        if not sql:
            raise ValueError("sql_step_missing_sql_template")
        if context.contains_unresolved_placeholders(sql, allow_step_refs=False):
            raise ValueError("sql_step_has_unresolved_placeholders")

        requires_approval, approval_reason = check_sql_needs_approval(sql)
        datasource_asset_id = context.coerce_int(step.raw_step.get("datasource_asset_id"))
        if datasource_asset_id is None:
            datasource_asset_id = context.coerce_int(
                asset_snapshot.get("datasource_asset_id")
            )
        datasource_asset = context.resolve_asset(datasource_asset_id)
        if datasource_asset is None or datasource_asset.asset_type != "datasource":
            raise ValueError("sql_step_missing_datasource_asset")

        datasource_config = datasource_asset.config or {}
        db_url = str(datasource_config.get("url") or "").strip()
        db_type = str(datasource_config.get("db_type") or "").strip().lower()
        if not db_url or not db_type:
            raise ValueError("sql_step_invalid_datasource_config")

        return {
            "sql": sql,
            "db_url": db_url,
            "db_type": db_type,
            "datasource_asset_id": int(datasource_asset.id),
            "requires_approval": requires_approval,
            "approval_reason": approval_reason,
        }
