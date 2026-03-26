"""Minimal SQL tool set for datamakepool specialist agents."""

from __future__ import annotations

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.datamakepool.sql_brain import SQLBrainService


class DatamakepoolSqlTool(FunctionTool):
    category = ToolCategory.DATABASE


def create_sql_tools(sql_brain: SQLBrainService | None = None) -> list[FunctionTool]:
    sql_brain = sql_brain or SQLBrainService()

    def sql_asset_check(task: str) -> dict:
        """Check whether the task may match an approved SQL asset."""
        return {
            "success": True,
            "matched": False,
            "message": f"SQL asset check placeholder for: {task}",
        }

    def execute_sql_plan(task: str) -> dict:
        """Generate a SQL-oriented data generation plan through SQL Brain."""
        result = sql_brain.generate_sql_plan(task)
        sql = result.get("sql")
        intermediate_sql = result.get("intermediate_sql")
        output = (
            f"SQL Brain generated SQL: {sql}"
            if sql
            else f"SQL Brain requested intermediate SQL: {intermediate_sql}"
        )
        return {
            "success": True,
            "output": output,
            "sql": sql,
            "intermediate_sql": intermediate_sql,
            "reasoning": result.get("reasoning"),
            "verification": result.get("verification"),
            "repair": result.get("repair"),
            "metadata": result.get("metadata"),
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
            description="Prepare SQL-oriented execution guidance for data generation tasks.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
