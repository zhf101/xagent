"""HTTP specialist agent for datamakepool."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.react import ReActPattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from ..tools import create_http_tools


class HttpExecutorAgent(VerticalAgent):
    def _get_domain_name(self) -> str:
        return "http_executor"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return (
            "你是 HTTP 造数专家。"
            "你的职责是处理 HTTP 接口相关的造数步骤，优先命中已治理 HTTP 资产，"
            "并输出安全、可重试、可校验的调用方案。"
        )

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return create_http_tools()

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        return [ReActPattern(llm=llm, is_sub_agent=True)]
