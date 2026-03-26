"""Minimal MCP tool set for datamakepool specialist agents."""

from __future__ import annotations

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool


class DatamakepoolMcpTool(FunctionTool):
    category = ToolCategory.MCP


def create_mcp_tools() -> list[FunctionTool]:
    def mcp_capability_list(task: str) -> dict:
        """List candidate MCP capabilities for the task."""
        return {
            "success": True,
            "capabilities": [],
            "message": f"MCP capability listing placeholder for: {task}",
        }

    def execute_mcp_plan(task: str) -> dict:
        """Prepare an MCP-oriented data generation plan."""
        return {
            "success": True,
            "output": f"MCP specialist prepared execution guidance for: {task}",
        }

    return [
        DatamakepoolMcpTool(
            mcp_capability_list,
            name="mcp_capability_list",
            description="List MCP capabilities relevant to a data generation task.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolMcpTool(
            execute_mcp_plan,
            name="execute_mcp_plan",
            description="Prepare MCP-oriented execution guidance for data generation tasks.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
