"""Minimal Dubbo tool set for datamakepool specialist agents."""

from __future__ import annotations

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool


class DatamakepoolDubboTool(FunctionTool):
    category = ToolCategory.BASIC


def create_dubbo_tools() -> list[FunctionTool]:
    def dubbo_asset_check(task: str) -> dict:
        """Check whether the task may match an approved Dubbo asset."""
        return {
            "success": True,
            "matched": False,
            "message": f"Dubbo asset check placeholder for: {task}",
        }

    def execute_dubbo_plan(task: str) -> dict:
        """Prepare a Dubbo-oriented data generation plan."""
        return {
            "success": True,
            "output": f"Dubbo specialist prepared execution guidance for: {task}",
        }

    return [
        DatamakepoolDubboTool(
            dubbo_asset_check,
            name="dubbo_asset_check",
            description="Check approved Dubbo assets before generating temporary service calls.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolDubboTool(
            execute_dubbo_plan,
            name="execute_dubbo_plan",
            description="Prepare Dubbo-oriented execution guidance for data generation tasks.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
