"""Datamakepool orchestrator vertical agent."""

from __future__ import annotations

from typing import Any, Sequence

from xagent.core.agent.pattern import AgentPattern
from xagent.core.agent.pattern.dag_plan_execute import DAGPlanExecutePattern
from xagent.core.agent.vertical_agent import VerticalAgent
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe import Tool

from .profile import DatamakepoolAgentProfile


class DatamakepoolOrchestratorAgent(VerticalAgent):
    """造数编排 vertical agent。

    这是 V3 多 agent 动态规划路径的入口 agent。
    当前阶段先完成：
    - vertical agent 注册
    - 专属 prompt
    - 专属 DAG pattern

    专业子 agent 和 AgentTool 组装在后续任务中继续补齐。
    """

    def __init__(self, name: str, llm: BaseLLM, memory=None, **kwargs: Any):
        # VerticalAgent 在 super().__init__ 早期就会调用 _get_domain_tools，
        # 因此这里先缓存构造期的 llm / memory，供 _get_domain_tools 使用。
        self._bootstrap_llm = llm
        self._bootstrap_memory = memory
        super().__init__(name=name, llm=llm, memory=memory, **kwargs)

    def _get_domain_name(self) -> str:
        return "datamakepool_orchestrator"

    def _get_domain_prompt(self, **kwargs: Any) -> str:
        return DatamakepoolAgentProfile.ORCHESTRATOR_PROMPT

    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        return DatamakepoolAgentProfile.get_orchestrator_tools(
            llm=self._bootstrap_llm,
            memory=self._bootstrap_memory,
            **kwargs,
        )

    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        workspace = kwargs.get("workspace")
        tracer = kwargs.get("tracer")
        task_id = kwargs.get("task_id")
        memory_store = kwargs.get("memory")

        if workspace is None:
            raise ValueError("DatamakepoolOrchestratorAgent requires workspace")

        return [
            DAGPlanExecutePattern(
                llm=llm,
                tracer=tracer,
                workspace=workspace,
                task_id=task_id,
                memory_store=memory_store,
            )
        ]

    def _get_domain_context(self, task: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "domain_mode": "data_generation",
            "datamakepool_task": task,
        }
