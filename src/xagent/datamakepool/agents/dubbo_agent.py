"""Dubbo specialist agent for datamakepool."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.react import ReActPattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from ..tools import create_dubbo_tools


class DubboExecutorAgent(VerticalAgent):
    def _get_domain_name(self) -> str:
        return "dubbo_executor"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return (
            "你是 Dubbo 造数专家。"
            "你的职责是处理 Dubbo 服务调用相关的造数步骤，优先命中已治理 Dubbo 资产，"
            "并生成可审计的服务调用方案。"
            "你只负责单个 step 的 Dubbo 求解、probe 分析或参数映射说明，"
            "不负责决定全局会话是否澄清、是否 compile、是否 execute。"
            "你必须优先使用已治理 Dubbo 资产，不得凭空捏造真实 Dubbo 执行细节。"
        )

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return create_dubbo_tools(
            db=kwargs.get("db"),
        )

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        return [ReActPattern(llm=llm, is_sub_agent=True)]
