"""Agent profile assembly for datamakepool orchestrator."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, List

from xagent.core.agent.tools.agent_tool import AgentTool
from xagent.core.tools.adapters.vibe import Tool

from .dubbo_agent import DubboExecutorAgent
from .http2mcp_agent import Http2McpExecutorAgent
from .http_agent import HttpExecutorAgent
from .sql_agent import SqlExecutorAgent


class DatamakepoolSpecialistAgentTool(AgentTool):
    """对 datamakepool 专业子 agent 增加结构化 contract 约束。

    目标：
    - 子 agent 只能处理 step-level problem contract
    - 不允许把全局会话编排上下文直接整包灌给子 agent
    - 让“只做局部求解”从 prompt 约束升级为工具层硬边界
    """

    _ALLOWED_PROBLEM_TYPES = {
        "step_execution",
        "probe_analysis",
        "mapping_explanation",
    }
    _FORBIDDEN_GLOBAL_KEYS = {
        "datamakepool_execution_plan",
        "datamakepool_reuse_hints",
        "datamakepool_compiled_dag",
        "datamakepool_runtime_contract",
        "datamakepool_conversation_ready",
        "recommended_action",
        "allowed_actions",
    }
    _EXECUTOR_BY_AGENT = {
        "sql_executor": {"sql"},
        "http_executor": {"http"},
        "dubbo_executor": {"dubbo"},
        "http2mcp_executor": {"http2mcp", "legacy_scenario"},
    }

    @classmethod
    def validate_contract_context(
        cls,
        *,
        agent_name: str,
        context: dict[str, Any] | None,
    ) -> None:
        if not isinstance(context, dict):
            raise ValueError(
                f"{agent_name} 缺少结构化 context，必须显式传入 datamakepool_subagent_contract"
            )
        forbidden = sorted(key for key in context.keys() if key in cls._FORBIDDEN_GLOBAL_KEYS)
        if forbidden:
            raise ValueError(
                f"{agent_name} 不接受全局会话编排字段: {', '.join(forbidden)}"
            )

        contract = context.get("datamakepool_subagent_contract")
        if not isinstance(contract, dict):
            raise ValueError(
                f"{agent_name} 缺少 datamakepool_subagent_contract"
            )
        if str(contract.get("contract_version") or "").strip() != "v1":
            raise ValueError(f"{agent_name} 只接受 contract_version=v1 的子任务契约")

        problem_type = str(contract.get("problem_type") or "").strip()
        if problem_type not in cls._ALLOWED_PROBLEM_TYPES:
            raise ValueError(
                f"{agent_name} 收到不支持的问题类型: {problem_type or 'empty'}"
            )

        step = contract.get("step")
        if not isinstance(step, dict):
            raise ValueError(f"{agent_name} 缺少 step 合约")
        step_key = str(step.get("step_key") or "").strip()
        executor_type = str(step.get("executor_type") or "").strip().lower()
        if not step_key:
            raise ValueError(f"{agent_name} 的 step 合约缺少 step_key")
        if not executor_type:
            raise ValueError(f"{agent_name} 的 step 合约缺少 executor_type")

        allowed_executors = cls._EXECUTOR_BY_AGENT.get(agent_name, set())
        if allowed_executors and executor_type not in allowed_executors:
            raise ValueError(
                f"{agent_name} 只能处理 {sorted(allowed_executors)}，但收到 {executor_type}"
            )

    async def run_json_async(self, args: dict[str, Any]) -> dict[str, Any]:
        task_args = self.args_type()(**args)
        self.validate_contract_context(
            agent_name=str(self.agent.name),
            context=task_args.context,
        )
        return await self._execute_agent(task_args)

    def with_bound_contract(self, contract: dict[str, Any]) -> "DatamakepoolSpecialistAgentTool":
        """返回一个已绑定 step contract 的 tool 代理。

        作用：
        - 把 step/problem contract 固化在工具层，而不是让 step 内的 LLM 自行拼接
        - 即使上游只传 task 文本，也会自动补齐 datamakepool_subagent_contract
        """

        return _BoundDatamakepoolSpecialistAgentTool(self, contract)


class _BoundDatamakepoolSpecialistAgentTool(DatamakepoolSpecialistAgentTool):
    """为单个 DAG step 绑定 contract 的轻量代理。"""

    def __init__(
        self,
        base_tool: DatamakepoolSpecialistAgentTool,
        contract: dict[str, Any],
    ) -> None:
        super().__init__(
            base_tool.agent,
            compact_mode=base_tool.compact_mode,
            custom_description=base_tool.description,
        )
        self._base_tool = base_tool
        self._bound_contract = deepcopy(dict(contract or {}))
        self._name = base_tool.name
        self._description = base_tool.description
        self._visibility = getattr(base_tool, "_visibility", self._visibility)

    async def run_json_async(self, args: dict[str, Any]) -> dict[str, Any]:
        merged_args = dict(args or {})
        merged_context = dict(merged_args.get("context") or {})
        merged_context["datamakepool_subagent_contract"] = deepcopy(
            self._bound_contract
        )
        merged_args["context"] = merged_context
        return await self._base_tool.run_json_async(merged_args)


class DatamakepoolAgentProfile:
    """造数编排 agent 的配置组装器。

    组装编排 agent 所需的 system prompt 和工具集（SQL / HTTP / Dubbo / MCP 子 agent）。
"""

    # ── classification 阶段的角色提示 ──
    # 这段 prompt 会被注入到 _build_classification_prompt 的 system_prompt 前缀。
    # 它的职责是告诉 LLM "你在造数平台里"，但 **不能** 暗示 LLM 跳过澄清直接规划。
    # 真正的澄清规则由 classification_data_generation.md 控制。
    CLASSIFICATION_ROLE_HINT = (
        "你当前处于智能造数平台。用户的请求将进入造数编排流程。\n"
        "在 classification 阶段，你的唯一任务是判断是否需要向用户澄清信息。\n"
        "请严格遵守后续的领域专属规则（classification_data_generation）来决定返回 chat 还是 plan。\n"
    )

    # ── 规划 / 执行阶段的完整角色 prompt ──
    # 这段 prompt 只在 _build_planning_prompt 和 DAG 执行阶段生效，
    # 不会出现在 classification 阶段，避免"我是规划者"的角色定义干扰澄清判断。
    ORCHESTRATOR_PROMPT = """
你是智能造数平台的编排代理。

你的职责是：
1. 作为全局 ReAct 主脑，决定 ask / probe / compile / approval / execute 的主顺序
2. 理解用户的造数需求
3. 在模板部分命中或未命中的情况下，把需求拆成可执行步骤
4. 当存在模板可复用步骤时，优先复用模板骨架，再补齐缺失步骤
5. 通过专业子 agent 完成 SQL / HTTP / Dubbo / MCP 执行

当前阶段：
- 你已经处于 data_generation 模式
- full_match 不会进入你
- partial_match 进入你时，说明已有模板覆盖部分需求；你必须优先保留并复用这些步骤
- no_match 进入你时，说明需要全量动态规划
- 你应优先产生清晰、可审计、可沉淀为模板的执行步骤
- 如果上下文中存在 datamakepool_reuse_hints / datamakepool_template_match 信息，
  应把其中的复用骨架视为已知前提，只对 missing_requirements 做补充规划
- SQL / HTTP / Dubbo / http2mcp 子 agent 只是 step-level 专家，不负责全局会话决策
- 不得把“是否继续澄清、是否 probe、是否 compile、是否 execute”的主顺序外包给子 agent

## 🚫 绝对禁止：用代码生成假数据

这是造数平台最核心的底线规则，违反即为严重缺陷：

- **禁止** 使用 execute_python_code / python_executor 或任何代码执行工具生成测试数据
- **禁止** 用 Python / JavaScript / 任何编程语言在内存中构造假数据再写入文件或数据库
- **禁止** 使用 Faker、random、uuid 等库在代码中批量生成数据
- **禁止** 把"生成数据"这个动作交给代码执行步骤

所有造数操作 **必须** 通过以下四个专业 executor 之一完成：
1. `sql_executor` — 通过 SQL 语句在真实数据库中插入/查询数据
2. `http_executor` — 通过 HTTP 接口调用业务系统的真实 API 造数
3. `dubbo_executor` — 通过 Dubbo 服务调用业务系统的真实服务造数
4. `http2mcp_executor` — 搜索存量造数场景并通过 http2mcp 网关执行

如果用户没有提供足够的业务信息（目标系统、表结构、接口地址、字段约束等），
你应该在规划中增加"信息收集"步骤，而不是用代码凭空捏造数据。

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
            DatamakepoolSpecialistAgentTool(
                sql_agent,
                custom_description=(
                    "执行 SQL 造数步骤。必须传入 context.datamakepool_subagent_contract，"
                    "problem_type 只能是 step_execution/probe_analysis/mapping_explanation。"
                ),
            ),
            DatamakepoolSpecialistAgentTool(
                http_agent,
                custom_description=(
                    "执行 HTTP 造数步骤。必须传入 context.datamakepool_subagent_contract，"
                    "不得把全局 ask/probe/compile/execute 顺序委托给该工具。"
                ),
            ),
            DatamakepoolSpecialistAgentTool(
                dubbo_agent,
                custom_description=(
                    "执行 Dubbo 造数步骤。必须传入 context.datamakepool_subagent_contract，"
                    "只允许局部步骤求解，不允许全局会话编排。"
                ),
            ),
            DatamakepoolSpecialistAgentTool(
                http2mcp_agent,
                custom_description=(
                    "搜索并执行存量造数场景。必须传入 context.datamakepool_subagent_contract，"
                    "只处理单个 step 的场景搜索/执行。"
                ),
            ),
        ]
