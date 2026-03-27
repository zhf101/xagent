"""SQL specialist agent for datamakepool."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.react import ReActPattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from ..sql_brain import SQLBrainService
from ..tools import create_sql_tools


class SqlExecutorAgent(VerticalAgent):
    def _get_domain_name(self) -> str:
        return "sql_executor"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return (
            "你是 SQL 造数专家。"
            "你的职责是处理 SQL 相关的造数步骤，优先检查已治理 SQL 资产，"
            "在需要时生成安全、可审计的 SQL 执行方案。"
        )

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return create_sql_tools(
            sql_brain=SQLBrainService(),
            db=kwargs.get("db"),
            system_short=kwargs.get("system_short"),
        )

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        return [ReActPattern(llm=llm, is_sub_agent=True)]
