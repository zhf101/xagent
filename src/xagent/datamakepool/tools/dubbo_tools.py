"""Dubbo specialist tool set for datamakepool."""

from __future__ import annotations

import json
from typing import Any

from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool

from ..assets import DubboAssetRepository, DubboAssetResolverService


class DatamakepoolDubboTool(FunctionTool):
    category = ToolCategory.BASIC


def create_dubbo_tools(*, db=None) -> list[FunctionTool]:
    resolver = DubboAssetResolverService(DubboAssetRepository(db)) if db is not None else None

    async def dubbo_asset_search(
        service_interface: str,
        method_name: str,
        system_short: str | None = None,
    ) -> dict:
        """Resolve a governed Dubbo asset before planning any service call."""
        if resolver is None:
            return {
                "success": False,
                "matched": False,
                "reason": "dubbo asset repository unavailable",
            }

        result = resolver.resolve(
            system_short=system_short,
            service_interface=service_interface,
            method_name=method_name,
        )
        return {
            "success": True,
            "matched": result.matched,
            "asset_id": result.asset_id,
            "asset_name": result.asset_name,
            "asset_config": result.config,
            "reason": result.reason,
        }

    async def dubbo_execution_plan(
        service_interface: str,
        method_name: str,
        system_short: str | None = None,
        parameter_values_json: str | None = None,
    ) -> dict:
        """Generate an auditable Dubbo execution plan based on governed asset metadata."""
        parameter_values: dict[str, Any] = {}
        if parameter_values_json:
            parameter_values = json.loads(parameter_values_json)

        asset_result = (
            resolver.resolve(
                system_short=system_short,
                service_interface=service_interface,
                method_name=method_name,
            )
            if resolver is not None
            else None
        )

        matched = bool(asset_result and asset_result.matched)
        config = asset_result.config if asset_result else None
        return {
            "success": True,
            "matched_asset": matched,
            "asset_id": asset_result.asset_id if asset_result else None,
            "asset_name": asset_result.asset_name if asset_result else None,
            "plan": {
                "execution_type": "dubbo_service_call_plan",
                "service_interface": service_interface,
                "method_name": method_name,
                "system_short": system_short or (config or {}).get("system_short"),
                "registry": (config or {}).get("registry"),
                "application": (config or {}).get("application"),
                "group": (config or {}).get("group"),
                "version": (config or {}).get("version"),
                "parameter_schema": (config or {}).get("parameter_schema", {}),
                "parameter_values": parameter_values,
                "attachments": (config or {}).get("attachments", {}),
                "timeout_ms": (config or {}).get("timeout_ms", 3000),
                "idempotent": (config or {}).get("idempotent", True),
                "approval_policy": (config or {}).get("approval_policy"),
                "risk_level": (config or {}).get("risk_level"),
            },
            "output": (
                f"Dubbo asset '{asset_result.asset_name}' matched; execution plan prepared."
                if matched
                else "No governed Dubbo asset matched; a governance gap remains."
            ),
        }

    return [
        DatamakepoolDubboTool(
            dubbo_asset_search,
            name="dubbo_asset_search",
            description="Search governed Dubbo assets by service interface and method before any temporary call planning.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolDubboTool(
            dubbo_execution_plan,
            name="dubbo_execution_plan",
            description="Prepare an auditable Dubbo execution plan from a governed Dubbo asset without actually executing the call.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
