"""
`DataMake Decision Provider`（datamake 决策提供器）模块。

这个模块负责承接 datamake 主脑“如何拿到一条 `NextActionDecision`”的整条链路：
- 先看运行期是否注入了单步决策
- 再看测试/烟测用的 mock decision 队列
- 最后才走真实 `llm.chat()` 调用

它的定位不是新的控制器，而是：
- 把 Pattern 里原本很重的“决策获取技术细节”抽出来
- 让 `DataMakeReActPattern` 更接近入口壳
- 让 `DataMakeDecisionRunner` 面对的是一个稳定的决策提供接口

明确不负责：
- 不构建 round context
- 不决定业务是否该 interaction / execution / terminate
- 不触碰 dispatch / guard / runtime / resource 控制律
"""

from __future__ import annotations

import json
import logging
from typing import Any

from json_repair import loads as repair_loads
from pydantic import ValidationError

from ...agent.context import AgentContext
from ...agent.exceptions import LLMNotAvailableError
from ...agent.trace import TraceCategory, Tracer, trace_action_end, trace_llm_call_start
from ...agent.utils.llm_utils import clean_messages
from ...model.chat.basic.base import BaseLLM
from ..contracts.decision import NextActionDecision
from .evidence_budget import EvidenceBudgetManager
from .prompt_builder import DataMakePromptBuilder

logger = logging.getLogger(__name__)


class DataMakeDecisionProvider:
    """
    `DataMakeDecisionProvider`（datamake 决策提供器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 `DecisionBuilder -> PromptBuilder/EvidenceBudget -> LLM`
      这一段技术桥接层

    职责边界：
    - 负责把“上下文 -> prompt -> LLM/注入决策 -> NextActionDecision”收口
    - 只处理技术获取路径，不新增任何业务判断
    - 保留 mock / injected decision 入口，便于测试与 smoke
    """

    def __init__(
        self,
        *,
        llm: BaseLLM | None,
        tracer: Tracer,
        prompt_builder: DataMakePromptBuilder,
        evidence_budget_manager: EvidenceBudgetManager,
    ) -> None:
        self.llm = llm
        self.tracer = tracer
        self.prompt_builder = prompt_builder
        self.evidence_budget_manager = evidence_budget_manager

    async def get_next_action_decision(
        self,
        task: str,
        round_context: dict[str, Any],
        context: AgentContext,
        task_id: str,
        step_id: str,
        round_id: int,
    ) -> NextActionDecision:
        """
        获取当前轮 `NextActionDecision`。

        优先级固定如下：
        1. `context.state["datamake_next_decision"]`
           适合人工或恢复逻辑注入单步 continuation
        2. `context.state["datamake_mock_decisions"]`
           适合测试和 smoke，不依赖真实 LLM
        3. 真实 `llm.chat()`
           用结构化 JSON 输出一条业务决策
        """

        injected_decision = context.state.pop("datamake_next_decision", None)
        if injected_decision is not None:
            return self.parse_decision_payload(injected_decision)

        mock_decisions = context.state.get("datamake_mock_decisions")
        if isinstance(mock_decisions, list) and mock_decisions:
            decision_payload = mock_decisions.pop(0)
            return self.parse_decision_payload(decision_payload)

        if self.llm is None:
            raise LLMNotAvailableError(
                "DataMakeReActPattern 未配置 LLM，无法生成下一动作决策。",
                context={
                    "pattern": "DataMakeReAct",
                    "task": task[:200],
                    "round_id": round_id,
                },
            )

        messages = self.build_llm_messages(task, round_context)
        messages = await self.check_and_compact_context(messages)
        await trace_llm_call_start(
            self.tracer,
            task_id,
            step_id,
            data={
                "pattern": "DataMakeReAct",
                "round_id": round_id,
                "model_name": getattr(self.llm, "model_name", "unknown"),
            },
        )
        response = await self.llm.chat(
            messages=clean_messages(messages),
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        await trace_action_end(
            self.tracer,
            task_id,
            step_id,
            TraceCategory.LLM,
            data={
                "pattern": "DataMakeReAct",
                "round_id": round_id,
                "response_preview": self.extract_content(response)[:500],
            },
        )
        return self.parse_decision_payload(response)

    def build_llm_messages(
        self,
        task: str,
        round_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        构建提供给 LLM 的当前轮消息。

        这里先做证据预算裁剪，再交给 PromptBuilder 负责表达，
        目的是让“证据进入 Prompt 的方式”和“Prompt 文案怎么写”保持清晰分层。
        """

        prompt_round_context = self.evidence_budget_manager.prepare_round_context_for_prompt(
            round_context
        )
        return self.prompt_builder.build_messages(task, prompt_round_context)

    def parse_decision_payload(self, payload: Any) -> NextActionDecision:
        """
        将外部 payload 解析为 `NextActionDecision`。

        显式兼容：
        - 已经是 `NextActionDecision`
        - `dict`
        - LLM 返回的 JSON 字符串
        """

        if isinstance(payload, NextActionDecision):
            return payload

        if isinstance(payload, dict):
            return NextActionDecision.model_validate(payload)

        if isinstance(payload, str):
            try:
                parsed_payload = repair_loads(payload, logging=False)
                return NextActionDecision.model_validate(parsed_payload)
            except ValidationError:
                raise
            except Exception as exc:
                logger.error("解析 NextActionDecision JSON 失败: %s", exc)
                raise ValueError(f"无法解析 NextActionDecision JSON: {exc}") from exc

        if isinstance(payload, list):
            raise ValueError("NextActionDecision 不能是 list，必须是 JSON object")

        if hasattr(payload, "get"):
            return NextActionDecision.model_validate(payload)

        raise TypeError(f"不支持的决策 payload 类型: {type(payload)}")

    def estimate_message_tokens(self, messages: list[dict[str, str]]) -> int:
        """估算当前消息 token 数。"""

        return self.evidence_budget_manager.estimate_message_tokens(messages)

    async def check_and_compact_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """在调用 LLM 前检查上下文长度，必要时执行压缩。"""

        return await self.evidence_budget_manager.check_and_compact_context(messages)

    async def compact_datamake_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """对 datamake 当前轮消息做压缩。"""

        return await self.evidence_budget_manager.compact_datamake_context(messages)

    def fallback_truncate_messages(
        self,
        messages: list[dict[str, str]],
        original_tokens: int,
    ) -> list[dict[str, str]]:
        """压缩失败时的兜底截断逻辑。"""

        return self.evidence_budget_manager.fallback_truncate_messages(
            messages,
            original_tokens,
        )

    def parse_compact_response(self, response: str) -> list[dict[str, str]]:
        """解析 compact 响应文本。"""

        return self.evidence_budget_manager.parse_compact_response(response)

    def extract_content(self, response: Any) -> str:
        """
        从 xagent LLM 返回结果中提取文本内容。

        这里保留宽松兼容，是因为不同模型适配器返回的对象形态并不完全一致，
        决策提供器必须在解析前先稳定拿到文本预览与 JSON 原文。
        """

        if response is None:
            return ""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            if "content" in response:
                return str(response["content"])
            return json.dumps(response, ensure_ascii=False, default=str)
        content = getattr(response, "content", None)
        if isinstance(content, str):
            return content
        return str(response)
