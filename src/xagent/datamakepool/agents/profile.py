"""Agent profile assembly for datamakepool orchestrator."""

from __future__ import annotations

from typing import List

from xagent.core.agent.tools.agent_tool import AgentTool
from xagent.core.tools.adapters.vibe import Tool

from .dubbo_agent import DubboExecutorAgent
from .http_agent import HttpExecutorAgent
from .mcp_agent import McpExecutorAgent
from .sql_agent import SqlExecutorAgent


class DatamakepoolAgentProfile:
    """造数编排 agent 的配置组装器。

    组装编排 agent 所需的 system prompt 和工具集（SQL / HTTP / Dubbo / MCP 子 agent）。
"""

    ORCHESTRATOR_PROMPT = """
你是智能造数平台的编排代理。

你的职责是：
1. 理解用户的造数需求
2. 在模板部分命中或未命中的情况下，把需求拆成可执行步骤
3. 当存在模板可复用步骤时，优先复用模板骨架，再补齐缺失步骤
4. 后续通过专业子 agent 完成 SQL / HTTP / Dubbo / MCP 执行

当前阶段：
- 你已经处于 data_generation 模式
- full_match 不会进入你
- partial_match 进入你时，说明已有模板覆盖部分需求；你必须优先保留并复用这些步骤
- no_match 进入你时，说明需要全量动态规划
- 你应优先产生清晰、可审计、可沉淀为模板的执行步骤
- 如果上下文中存在 datamakepool_execution_plan / datamakepool_template_match 信息，
  应把 reusable_steps 视为已知可复用骨架，只对 missing_requirements 做补充规划
""".strip()

    @staticmethod
    def get_orchestrator_tools(llm, memory=None, **kwargs: object) -> List[Tool]:
        """组装编排 agent 的工具集合（四个专业子 agent 包装为 AgentTool）。"""
        sql_agent = SqlExecutorAgent(name="sql_executor", llm=llm, memory=memory)
        http_agent = HttpExecutorAgent(
            name="http_executor", llm=llm, memory=memory, db=kwargs.get("db")
        )
        dubbo_agent = DubboExecutorAgent(
            name="dubbo_executor", llm=llm, memory=memory, db=kwargs.get("db")
        )
        mcp_agent = McpExecutorAgent(name="mcp_executor", llm=llm, memory=memory)

        return [
            AgentTool(sql_agent, custom_description="执行 SQL 造数任务"),
            AgentTool(http_agent, custom_description="调用 HTTP 接口造数"),
            AgentTool(dubbo_agent, custom_description="调用 Dubbo 服务造数"),
            AgentTool(mcp_agent, custom_description="调用存量造数 MCP 能力"),
        ]
