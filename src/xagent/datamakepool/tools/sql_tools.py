"""Minimal SQL tool set for datamakepool specialist agents."""

from __future__ import annotations

from sqlalchemy.orm import Session

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.datamakepool.assets.repositories import SqlAssetRepository
from xagent.datamakepool.assets.service import SqlAssetResolverService
from xagent.datamakepool.interceptors import check_sql_needs_approval
from xagent.datamakepool.sql_brain import SQLBrainService


class DatamakepoolSqlTool(FunctionTool):
    category = ToolCategory.DATABASE


def create_sql_tools(
    sql_brain: SQLBrainService | None = None,
    db: Session | None = None,
    system_short: str | None = None,
) -> list[FunctionTool]:
    sql_brain = sql_brain or SQLBrainService()

    def sql_asset_check(task: str) -> dict:
        """Check whether the task may match an approved SQL asset."""
        if db is None:
            return {
                "success": False,
                "matched": False,
                "message": "No database session available for SQL asset lookup.",
            }
        result = SqlAssetResolverService(SqlAssetRepository(db)).resolve(
            task=task,
            system_short=system_short,
        )
        if result.matched:
            return {
                "success": True,
                "matched": True,
                "asset_id": result.asset_id,
                "asset_name": result.asset_name,
                "config": result.config,
                "reason": result.reason,
            }
        return {
            "success": True,
            "matched": False,
            "reason": result.reason,
            "top_candidates": result.top_candidates or [],
            "candidate_count": result.candidate_count,
        }

    def execute_sql_plan(task: str) -> dict:
        """Generate a SQL execution plan through SQL Brain.

        This function generates a SQL plan only — it does NOT execute any SQL.
        The returned SQL should be reviewed and submitted for approval if required
        before actual execution.
        """
        result = sql_brain.generate_sql_plan(task)
        sql = result.get("sql")
        intermediate_sql = result.get("intermediate_sql")
        output = (
            f"SQL Brain generated SQL: {sql}"
            if sql
            else f"SQL Brain requested intermediate SQL: {intermediate_sql}"
        )
        approval_required, approval_reason = check_sql_needs_approval(sql or intermediate_sql or "")
        return {
            "success": True,
            "executed": False,
            "output": output,
            "sql": sql,
            "intermediate_sql": intermediate_sql,
            "reasoning": result.get("reasoning"),
            "verification": result.get("verification"),
            "repair": result.get("repair"),
            "metadata": result.get("metadata"),
            "requires_approval": approval_required,
            "approval_reason": approval_reason,
        }

    return [
        DatamakepoolSqlTool(
            sql_asset_check,
            name="sql_asset_check",
            description="Check approved SQL assets before generating temporary SQL.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolSqlTool(
            execute_sql_plan,
            name="execute_sql_plan",
            description="Generate a SQL execution plan (plan only, not executed). Returns generated SQL for review before execution.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
