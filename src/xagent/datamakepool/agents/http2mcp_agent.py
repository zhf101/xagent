"""Http2Mcp specialist agent for datamakepool."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.react import ReActPattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from ..tools.legacy_scenario_meta_tools import create_http2mcp_meta_tools

_PROMPT = """
你是存量造数平台的执行专家，通过 http2mcp 网关调用经过治理的存量造数场景。

## 工作流程（必须按序执行）

1. [搜索] legacy_scenario_catalog_search
   - 用任务描述作为 query 搜索存量场景目录（top_k=5）
   - 不加载真实 MCP tool，仅返回摘要

2. [核查] legacy_scenario_catalog_get
   - 对搜索结果中高分候选（match_score >= 0.3）逐一获取完整 schema
   - 确认参数是否与当前步骤匹配

3. [加载] legacy_scenario_tool_loader
   - 将确认可用的场景 tool 加载到当前 agent（每次最多 5 个）
   - risk_level=high 的场景加载后须在输出中标注"需要审批"

4. [执行] 调用已加载的 MCP tool 完成造数

## 部分命中处理

当搜索结果只能覆盖用户需求的部分步骤时：
- covered_steps: 列出有存量场景可用的步骤，附上 scenario_id 和 scenario_name
- missing_steps: 列出无法匹配的步骤及其类型（sql/http/dubbo），供 orchestrator 分配给其他 executor
- 不得强行使用不匹配的场景，宁可声明 missing

## 约束

- 搜索无结果时，直接输出 {"covered_steps": [], "missing_steps": [<全部步骤>]}
- 每轮最多加载 5 个场景 tool
- 不得跳过搜索步骤直接执行
""".strip()


class Http2McpExecutorAgent(VerticalAgent):
    """通过 http2mcp 网关执行存量造数场景的专家 agent。

    使用分层渐进披露（meta tools）模式：
    1. 先搜索场景目录（不加载真实 tool）
    2. 按需获取场景详情
    3. 确认后加载具体 MCP tool
    4. 调用已加载 tool 执行造数
    """

    def _get_domain_name(self) -> str:
        return "http2mcp_executor"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return _PROMPT

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return create_http2mcp_meta_tools(
            mcp_configs=kwargs.get("mcp_configs"),
            user_id=kwargs.get("user_id", 0),
            agent_service=kwargs.get("agent_service"),
            db=kwargs.get("db"),
        )

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        return [ReActPattern(llm=llm, is_sub_agent=True)]
