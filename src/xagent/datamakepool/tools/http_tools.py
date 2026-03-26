"""Minimal HTTP tool set for datamakepool specialist agents."""

from __future__ import annotations

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool


class DatamakepoolHttpTool(FunctionTool):
    category = ToolCategory.BASIC


def create_http_tools() -> list[FunctionTool]:
    def http_asset_check(task: str) -> dict:
        """Check whether the task may match an approved HTTP asset."""
        return {
            "success": True,
            "matched": False,
            "message": f"HTTP asset check placeholder for: {task}",
        }

    def execute_http_plan(task: str) -> dict:
        """Prepare an HTTP-oriented data generation plan."""
        return {
            "success": True,
            "output": f"HTTP specialist prepared execution guidance for: {task}",
        }

    return [
        DatamakepoolHttpTool(
            http_asset_check,
            name="http_asset_check",
            description="Check approved HTTP assets before calling external APIs.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolHttpTool(
            execute_http_plan,
            name="execute_http_plan",
            description="Prepare HTTP-oriented execution guidance for data generation tasks.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
