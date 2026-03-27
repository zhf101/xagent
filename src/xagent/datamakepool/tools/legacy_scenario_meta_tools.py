"""Task-local progressive disclosure tools for legacy data-generation scenarios."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from time import time
from typing import Any, Dict, List, Optional

from mcp.types import Tool as MCPTool

from xagent.core.agent.service import AgentService
from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.core.tools.adapters.vibe.mcp_adapter import MCPToolAdapter
from xagent.core.tools.core.mcp.sessions import Connection, create_session
from xagent.datamakepool.recall_funnel import RecallFunnelExecutor, RecallQuery, load_default_embedding_adapter
from xagent.datamakepool.recall_funnel.adapters import LegacyScenarioRecallAdapter
from xagent.datamakepool.tools.legacy_scenario_catalog_registry import (
    LegacyScenarioCatalogRegistry,
    record_legacy_scenario_execution,
)

logger = logging.getLogger(__name__)

CATALOG_CACHE_SECONDS = 300
LEGACY_SERVER_HINTS = ("legacy", "scenario", "history", "http2mcp", "造数")


class LegacyScenarioMetaTool(FunctionTool):
    category = ToolCategory.MCP


class LegacyScenarioToolAdapter(MCPToolAdapter):
    def __init__(
        self,
        *,
        scenario_id: str,
        user_id: int,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._scenario_id = scenario_id
        self._user_id = user_id

    async def run_json_async(self, args: Dict[str, Any]) -> Any:
        result = await super().run_json_async(args)
        is_error = bool(result.get("is_error")) if isinstance(result, dict) else False
        record_legacy_scenario_execution(
            self._user_id, self._scenario_id, success=not is_error
        )
        return result


@dataclass
class LegacyScenarioCatalogEntry:
    scenario_id: str
    scenario_name: str
    server_name: str
    tool_name: str
    tool_load_ref: str
    description: str
    system_short: Optional[str]
    business_tags: list[str]
    entity_tags: list[str]
    input_schema_summary: list[str]
    status: str = "active"
    approval_policy: Optional[str] = None
    risk_level: Optional[str] = None
    usage_count: int = 0
    success_rate: int = 0
    last_used_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "tool_load_ref": self.tool_load_ref,
            "description": self.description,
            "system_short": self.system_short,
            "business_tags": self.business_tags,
            "entity_tags": self.entity_tags,
            "input_schema_summary": self.input_schema_summary,
            "status": self.status,
            "approval_policy": self.approval_policy,
            "risk_level": self.risk_level,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "last_used_at": self.last_used_at,
        }


class LegacyScenarioCatalogService:
    """Discovers and searches historical scenario MCP capabilities for one task."""

    def __init__(
        self,
        *,
        mcp_configs: list[dict[str, Any]],
        user_id: int,
        agent_service: AgentService | None,
        db: Any | None = None,
        db_dir: str | None = None,
        embedding_model: Any | None = None,
    ):
        self._mcp_configs = mcp_configs
        self._user_id = user_id
        self._agent_service = agent_service
        self._db = db
        self._catalog: list[LegacyScenarioCatalogEntry] = []
        self._catalog_loaded_at = 0.0
        self._indexer = None
        self._retriever = None
        if embedding_model is None and db is not None and hasattr(db, "query"):
            embedding_model = load_default_embedding_adapter(db, user_id)
        if db_dir is None and embedding_model is not None:
            db_dir = "data/lancedb"
        if db_dir is not None and embedding_model is not None:
            from xagent.datamakepool.tools.legacy_scenario_indexer import LegacyScenarioIndexer
            from xagent.datamakepool.tools.legacy_scenario_retriever import LegacyScenarioRetriever
            self._indexer = LegacyScenarioIndexer(db_dir, embedding_model)
            self._retriever = LegacyScenarioRetriever(db_dir, embedding_model)

    def _filter_legacy_configs(self) -> list[dict[str, Any]]:
        legacy_configs = []
        for config in self._mcp_configs:
            joined = " ".join(
                [
                    str(config.get("name") or ""),
                    str(config.get("description") or ""),
                ]
            ).lower()
            if any(hint in joined for hint in LEGACY_SERVER_HINTS):
                legacy_configs.append(config)

        return legacy_configs if legacy_configs else list(self._mcp_configs)

    def _build_connection_map(self) -> dict[str, Connection]:
        connections: dict[str, Connection] = {}
        for config in self._filter_legacy_configs():
            connection: dict[str, Any] = {
                "transport": config["transport"],
                **config.get("config", {}),
            }
            connections[str(config["name"])] = connection  # type: ignore[assignment]
        return connections

    @staticmethod
    def _scenario_name_from_tool(tool_name: str) -> str:
        cleaned = re.sub(r"[_\-]+", " ", tool_name).strip()
        return cleaned or tool_name

    @staticmethod
    def _extract_system_short(text: str) -> Optional[str]:
        match = re.search(r"\b(crm|oms|erp|tms|wms|cms|bi)\b", text.lower())
        return match.group(1) if match else None

    @staticmethod
    def _extract_tags(tool_name: str, description: str) -> tuple[list[str], list[str]]:
        source = f"{tool_name} {description}".lower()
        business_tags = [
            tag
            for tag in ["订单", "用户", "交易", "会员", "库存", "物流", "支付"]
            if tag in source
        ]
        entity_tags = [
            tag
            for tag in ["order", "user", "transaction", "member", "inventory", "shipment", "payment"]
            if tag in source
        ]
        return business_tags, entity_tags

    async def _discover_catalog(self) -> list[LegacyScenarioCatalogEntry]:
        if self._catalog and time() - self._catalog_loaded_at < CATALOG_CACHE_SECONDS:
            return self._catalog

        entries: list[LegacyScenarioCatalogEntry] = []
        connection_map = self._build_connection_map()
        for server_name, connection in connection_map.items():
            try:
                async with create_session(connection) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    mcp_tools = tools_result.tools if tools_result.tools else []
                    for tool in mcp_tools:
                        if not self._looks_like_legacy_scenario(server_name, tool):
                            continue
                        entries.append(self._tool_to_entry(server_name, tool))
            except Exception as exc:
                logger.warning(
                    "Failed to discover legacy scenario tools from %s: %s",
                    server_name,
                    exc,
                )

        self._catalog = entries
        self._catalog_loaded_at = time()
        return entries

    async def sync_catalog(self) -> dict[str, Any]:
        discovered = await self._discover_catalog()
        registry = self._registry()
        synced_at = datetime.now(timezone.utc)
        if registry is not None:
            registry.upsert_entries(
                [
                    {
                        **entry.to_dict(),
                        "last_synced_at": synced_at,
                    }
                    for entry in discovered
                ]
            )

        if self._indexer is not None:
            self._indexer.index_all([entry.to_dict() for entry in discovered])

        return {
            "success": True,
            "count": len(discovered),
            "synced_at": synced_at.isoformat(),
        }

    def _registry(self) -> LegacyScenarioCatalogRegistry | None:
        if self._db is None:
            return None
        return LegacyScenarioCatalogRegistry(self._db, self._user_id)

    async def _get_catalog(self) -> list[LegacyScenarioCatalogEntry]:
        registry = self._registry()
        if registry is None:
            return await self._discover_catalog()

        if registry.is_stale():
            discovered = await self._discover_catalog()
            registry.upsert_entries(
                [
                    {
                        **entry.to_dict(),
                        "last_synced_at": datetime.now(timezone.utc),
                    }
                    for entry in discovered
                ]
            )
            if self._indexer is not None:
                self._indexer.index_all([e.to_dict() for e in discovered])

        rows = registry.list_entries()
        if rows:
            return [
                LegacyScenarioCatalogEntry(
                    scenario_id=row.scenario_id,
                    scenario_name=row.scenario_name,
                    server_name=row.server_name,
                    tool_name=row.tool_name,
                    tool_load_ref=row.tool_load_ref,
                    description=row.description or "",
                    system_short=row.system_short,
                    business_tags=list(row.business_tags or []),
                    entity_tags=list(row.entity_tags or []),
                    input_schema_summary=list(row.input_schema_summary or []),
                    status=row.status,
                    approval_policy=row.approval_policy,
                    risk_level=row.risk_level,
                    usage_count=int(row.usage_count or 0),
                    success_rate=int(row.success_rate or 0),
                    last_used_at=row.last_used_at.isoformat()
                    if row.last_used_at
                    else None,
                )
                for row in rows
            ]

        return await self._discover_catalog()

    def _looks_like_legacy_scenario(self, server_name: str, tool: MCPTool) -> bool:
        haystack = " ".join(
            [server_name, tool.name, tool.description or ""]
        ).lower()
        return any(hint in haystack for hint in LEGACY_SERVER_HINTS) or bool(
            re.search(r"(order|user|transaction|场景|造数)", haystack)
        )

    def _tool_to_entry(self, server_name: str, tool: MCPTool) -> LegacyScenarioCatalogEntry:
        description = tool.description or ""
        business_tags, entity_tags = self._extract_tags(tool.name, description)
        input_schema = tool.inputSchema if hasattr(tool, "inputSchema") else {}
        input_summary = []
        if isinstance(input_schema, dict):
            for field_name in list((input_schema.get("properties") or {}).keys())[:8]:
                input_summary.append(str(field_name))

        scenario_id = f"{server_name}::{tool.name}"
        risk_level = (
            "high"
            if any(
                token in description.lower()
                for token in ["delete", "drop", "truncate", "write", "修改"]
            )
            else "low"
        )
        approval_policy = "manual_review" if risk_level == "high" else "none"
        return LegacyScenarioCatalogEntry(
            scenario_id=scenario_id,
            scenario_name=self._scenario_name_from_tool(tool.name),
            server_name=server_name,
            tool_name=tool.name,
            tool_load_ref=scenario_id,
            description=description,
            system_short=self._extract_system_short(f"{tool.name} {description}"),
            business_tags=business_tags,
            entity_tags=entity_tags,
            input_schema_summary=input_summary,
            approval_policy=approval_policy,
            risk_level=risk_level,
        )

    async def search(
        self, query: str, system_short: Optional[str] = None, top_k: int = 6
    ) -> list[dict[str, Any]]:
        catalog = await self._get_catalog()
        adapter = LegacyScenarioRecallAdapter(
            catalog=catalog,
            retriever=self._retriever,
        )
        execution = RecallFunnelExecutor[LegacyScenarioCatalogEntry]().run(
            adapter,
            RecallQuery(
                query_text=query,
                system_short=system_short,
                top_k=top_k,
            ),
        )
        results = adapter.finalize(
            RecallQuery(
                query_text=query,
                system_short=system_short,
                top_k=top_k,
            ),
            execution.candidates,
        )
        for item in results:
            item["recall_strategy"] = execution.recall_strategy
            item["used_ann"] = execution.used_ann
            item["used_fallback"] = execution.used_fallback
            item["stage_results"] = [stage.to_dict() for stage in execution.stage_results]
        return results

    async def get(self, scenario_id: str) -> Optional[dict[str, Any]]:
        registry = self._registry()
        if registry is not None:
            if registry.is_stale():
                await self._get_catalog()
            row = registry.get_entry(scenario_id)
            if row is not None:
                return {
                    "scenario_id": row.scenario_id,
                    "scenario_name": row.scenario_name,
                    "server_name": row.server_name,
                    "tool_name": row.tool_name,
                    "tool_load_ref": row.tool_load_ref,
                    "description": row.description or "",
                    "system_short": row.system_short,
                    "business_tags": row.business_tags or [],
                    "entity_tags": row.entity_tags or [],
                    "input_schema_summary": row.input_schema_summary or [],
                    "status": row.status,
                    "approval_policy": row.approval_policy,
                    "risk_level": row.risk_level,
                    "usage_count": int(row.usage_count or 0),
                    "success_rate": int(row.success_rate or 0),
                    "last_used_at": row.last_used_at.isoformat()
                    if row.last_used_at
                    else None,
                }

        catalog = await self._get_catalog()
        for entry in catalog:
            if entry.scenario_id == scenario_id:
                return entry.to_dict()
        return None

    async def list_catalog(self) -> list[dict[str, Any]]:
        catalog = await self._get_catalog()
        return [entry.to_dict() for entry in catalog]

    async def load_tools(self, scenario_ids: list[str]) -> dict[str, Any]:
        if self._agent_service is None:
            return {
                "success": False,
                "loaded_tools": [],
                "loaded_count": 0,
                "skipped": [
                    {
                        "scenario_id": scenario_id,
                        "reason": "agent_service_not_available",
                    }
                    for scenario_id in scenario_ids
                ],
            }
        catalog = await self._get_catalog()
        selected = [entry for entry in catalog if entry.scenario_id in set(scenario_ids)]

        grouped: dict[str, list[LegacyScenarioCatalogEntry]] = {}
        for entry in selected:
            grouped.setdefault(entry.server_name, []).append(entry)

        loaded_tool_names: list[str] = []
        skipped: list[dict[str, str]] = []
        existing_names = {
            getattr(tool, "name", None)
            for tool in self._agent_service.tools
            if hasattr(tool, "name")
        }

        for server_name, entries in grouped.items():
            connection = self._build_connection_map().get(server_name)
            if connection is None:
                skipped.extend(
                    {
                        "scenario_id": entry.scenario_id,
                        "reason": "server_not_found",
                    }
                    for entry in entries
                )
                continue

            target_names = {entry.tool_name for entry in entries}
            try:
                async with create_session(connection) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    mcp_tools = tools_result.tools if tools_result.tools else []
                    safe_server_name = re.sub(r"[^a-zA-Z0-9_]+", "_", server_name)
                    for mcp_tool in mcp_tools:
                        if mcp_tool.name not in target_names:
                            continue
                        scenario_id = f"{server_name}::{mcp_tool.name}"
                        adapter = LegacyScenarioToolAdapter(
                            scenario_id=scenario_id,
                            user_id=self._user_id,
                            mcp_tool=mcp_tool,
                            connection=connection,
                            name_prefix=f"legacy_{safe_server_name}_",
                            visibility=ToolVisibility.PRIVATE,
                            allow_users=[str(self._user_id)],
                        )
                        if adapter.name in existing_names:
                            continue
                        self._agent_service.add_tool(adapter)
                        existing_names.add(adapter.name)
                        loaded_tool_names.append(adapter.name)
            except Exception as exc:
                skipped.extend(
                    {
                        "scenario_id": entry.scenario_id,
                        "reason": f"load_failed:{exc}",
                    }
                    for entry in entries
                )

        return {
            "success": True,
            "loaded_tools": loaded_tool_names,
            "loaded_count": len(loaded_tool_names),
            "skipped": skipped,
        }


DEFAULT_HTTP2MCP_CONFIG = [
    {
        "name": "http2mcp",
        "transport": "streamable_http",
        "config": {"url": "http://127.0.0.1:8000/mcp"},
    }
]


def create_http2mcp_meta_tools(
    *,
    mcp_configs: list[dict[str, Any]] | None = None,
    user_id: int = 0,
    agent_service: AgentService | None = None,
    db: Any | None = None,
) -> list[LegacyScenarioMetaTool]:
    """同步工厂：为 Http2McpExecutorAgent 创建分层渐进披露的 meta tools。

    工具调用流程（LLM 必须按序）：
    1. legacy_scenario_catalog_search  — 搜索候选场景，不加载真实 tool
    2. legacy_scenario_catalog_get     — 获取单个场景详细 schema
    3. legacy_scenario_tool_loader     — 确认后加载具体 MCP tool 到当前 agent
    4. 调用已加载的 tool 完成造数
    """
    resolved_configs = mcp_configs if mcp_configs is not None else DEFAULT_HTTP2MCP_CONFIG
    catalog_service = LegacyScenarioCatalogService(
        mcp_configs=resolved_configs,
        user_id=user_id,
        agent_service=agent_service,
        db=db,
    )

    async def legacy_scenario_catalog_search(
        query: str, system_short: str | None = None, top_k: int = 5
    ) -> dict:
        """【第1步】按任务描述搜索存量造数场景目录，返回摘要列表（不加载真实 MCP tool）。

        返回字段：scenario_id, scenario_name, description, system_short,
        input_schema_summary, risk_level, match_score。
        - 若结果为空说明无存量场景，输出 missing_steps 供 orchestrator 处理。
        - 若结果只能覆盖部分步骤，在回复里区分 covered_steps 和 missing_steps。
        """
        results = await catalog_service.search(query, system_short, top_k)
        return {"success": True, "results": results, "count": len(results)}

    async def legacy_scenario_catalog_get(scenario_id: str) -> dict:
        """【第2步】获取单个存量场景的完整 schema 和参数说明，用于确认是否符合当前步骤需求。"""
        result = await catalog_service.get(scenario_id)
        return {"success": result is not None, "scenario": result}

    async def legacy_scenario_tool_loader(scenario_ids: list[str]) -> dict:
        """【第3步】将选中的存量场景 MCP tool 加载到当前 agent，加载后即可直接调用。

        每次最多加载 5 个。risk_level=high 的场景加载后须在输出中标注，等待审批。
        """
        if len(scenario_ids) > 5:
            scenario_ids = scenario_ids[:5]
        return await catalog_service.load_tools(scenario_ids)

    return [
        LegacyScenarioMetaTool(
            legacy_scenario_catalog_search,
            name="legacy_scenario_catalog_search",
            description=(
                "【第1步】搜索 http2mcp 存量造数场景目录。"
                "返回场景摘要（scenario_id/描述/参数概要/风险级别），不加载真实 MCP tool，不消耗额外上下文。"
                "搜索无结果时输出 missing_steps；部分命中时区分 covered_steps 和 missing_steps。"
            ),
            visibility=ToolVisibility.PRIVATE,
        ),
        LegacyScenarioMetaTool(
            legacy_scenario_catalog_get,
            name="legacy_scenario_catalog_get",
            description=(
                "【第2步】获取单个存量造数场景的完整 schema 和参数说明。"
                "在 tool_loader 加载前用于确认场景是否满足当前步骤需求。"
            ),
            visibility=ToolVisibility.PRIVATE,
        ),
        LegacyScenarioMetaTool(
            legacy_scenario_tool_loader,
            name="legacy_scenario_tool_loader",
            description=(
                "【第3步】将选定存量造数场景的 MCP tool 加载到当前 agent（每次最多5个）。"
                "加载完成后直接调用已加载的 tool 完成造数。risk_level=high 的场景须标注等待审批。"
            ),
            visibility=ToolVisibility.PRIVATE,
        ),
    ]


async def create_legacy_scenario_meta_tools(
    *,
    mcp_configs: list[dict[str, Any]],
    user_id: int,
    agent_service: AgentService,
    db: Any | None = None,
) -> list[LegacyScenarioMetaTool]:
    catalog_service = LegacyScenarioCatalogService(
        mcp_configs=mcp_configs,
        user_id=user_id,
        agent_service=agent_service,
        db=db,
    )

    async def legacy_scenario_catalog_search(
        query: str, system_short: str | None = None, top_k: int = 6
    ) -> dict:
        """Search the governed legacy scenario catalog before exposing real MCP tools."""
        results = await catalog_service.search(query, system_short, top_k)
        return {"success": True, "results": results, "count": len(results)}

    async def legacy_scenario_catalog_get(scenario_id: str) -> dict:
        """Get detailed metadata for one legacy scenario catalog entry."""
        result = await catalog_service.get(scenario_id)
        return {"success": result is not None, "scenario": result}

    async def legacy_scenario_tool_loader(scenario_ids: list[str]) -> dict:
        """Load selected legacy scenario MCP tools into the current task agent only."""
        return await catalog_service.load_tools(scenario_ids)

    return [
        LegacyScenarioMetaTool(
            legacy_scenario_catalog_search,
            name="legacy_scenario_catalog_search",
            description="Search governed historical data-generation scenarios without exposing all MCP tools at once.",
            visibility=ToolVisibility.PRIVATE,
        ),
        LegacyScenarioMetaTool(
            legacy_scenario_catalog_get,
            name="legacy_scenario_catalog_get",
            description="Inspect metadata for one historical data-generation scenario.",
            visibility=ToolVisibility.PRIVATE,
        ),
        LegacyScenarioMetaTool(
            legacy_scenario_tool_loader,
            name="legacy_scenario_tool_loader",
            description="Dynamically load a small set of historical scenario MCP tools into the current task agent.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
