"""Agent profile assembly for datamakepool orchestrator."""

from __future__ import annotations

from typing import List

from xagent.core.agent.tools.agent_tool import AgentTool
from xagent.core.tools.adapters.vibe import Tool

from .dubbo_agent import DubboExecutorAgent
from .http2mcp_agent import Http2McpExecutorAgent
from .http_agent import HttpExecutorAgent
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

## 存量造数场景优先策略

规划 DAG 之前，必须先评估是否存在可用的存量造数场景：
- 完全命中：用户需求的所有步骤都能在 http2mcp_executor 的存量目录中找到匹配场景
  → 所有步骤交给 http2mcp_executor 执行
- 部分命中：存量目录覆盖部分步骤（http2mcp_executor 返回 covered_steps + missing_steps）
  → covered_steps 交给 http2mcp_executor（在 step context 中传入对应 scenario_id）
  → missing_steps 按步骤类型分配给 sql_executor / http_executor / dubbo_executor
  → DAG 中正确设置 depends_on，保证执行顺序
- 完全未命中：http2mcp_executor 返回空 covered_steps
  → 直接按步骤类型分配给对应专业 executor
""".strip()

    @staticmethod
    def get_orchestrator_tools(llm, memory=None, **kwargs: object) -> List[Tool]:
        """组装编排 agent 的工具集合（四个专业子 agent 包装为 AgentTool）。"""
        sql_agent = SqlExecutorAgent(
            name="sql_executor",
            llm=llm,
            memory=memory,
            db=kwargs.get("db"),
            user_id=kwargs.get("user_id"),
            system_short=kwargs.get("system_short"),
            db_type=kwargs.get("db_type"),
            sql_brain_llm=llm,
        )
        http_agent = HttpExecutorAgent(
            name="http_executor", llm=llm, memory=memory, db=kwargs.get("db")
        )
        dubbo_agent = DubboExecutorAgent(
            name="dubbo_executor", llm=llm, memory=memory, db=kwargs.get("db")
        )
        http2mcp_agent = Http2McpExecutorAgent(
            name="http2mcp_executor",
            llm=llm,
            memory=memory,
            mcp_configs=kwargs.get("mcp_configs"),
            user_id=kwargs.get("user_id", 0),
            agent_service=kwargs.get("agent_service"),
            db=kwargs.get("db"),
        )

        return [
            AgentTool(sql_agent, custom_description="执行 SQL 造数任务"),
            AgentTool(http_agent, custom_description="调用 HTTP 接口造数"),
            AgentTool(dubbo_agent, custom_description="调用 Dubbo 服务造数"),
            AgentTool(
                http2mcp_agent,
                custom_description="优先搜索存量造数场景并通过 http2mcp 网关执行，支持部分命中后将缺口步骤交给其他 executor",
            ),
        ]
