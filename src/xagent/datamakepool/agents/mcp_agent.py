"""MCP specialist agent for datamakepool."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.react import ReActPattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from ..tools import create_mcp_tools


class McpExecutorAgent(VerticalAgent):
    def _get_domain_name(self) -> str:
        return "mcp_executor"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return (
            "你是 MCP 造数专家。"
            "你的职责是调用存量造数平台暴露的 MCP 能力完成造数步骤，"
            "并选择最合适的 capability。"
        )

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return create_mcp_tools()

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        return [ReActPattern(llm=llm, is_sub_agent=True)]
