"""
`DataMake Decision Runner`（datamake 决策循环执行器）模块。

这个模块承接 `DataMakeReActPattern` 里最核心的那段 for-loop 主循环，
目标是把“入口壳”与“纯决策循环”逐步分开。

职责边界：
- 负责单次 datamake run 中的迭代控制
- 负责把 round context、decision、dispatch outcome 串起来
- 负责把 observation / waiting result / final result 回流到正确宿主

明确不负责：
- 不装配基础依赖
- 不处理对外入口 trace 的 task_start / user_message
- 不替主脑决定下一步动作
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from ...agent.context import AgentContext
from ...agent.exceptions import LLMNotAvailableError, MaxIterationsError
from ...agent.trace import (
    Tracer,
    trace_error,
)
from ..contracts.decision import NextActionDecision
from ..contracts.interaction import InteractionTicket
from ..contracts.observation import ObservationEnvelope
from .orchestrator import DecisionBuilder


@dataclass(slots=True)
class DataMakeRunInput:
    """
    `DataMakeRunInput`（单次运行输入）。

    这个对象只承载“本次 run 真正变化的输入事实”，
    目的是把原来散落在 `run()` 参数列表里的运行上下文收拢成一个明确载体。

    当前放在这里的字段满足两个条件：
    - 它们属于一次 run 的输入，而不是 Runner 的长期依赖
    - 它们会随着任务、上下文或本次构建器实例变化而变化
    """

    task: str
    context: AgentContext
    decision_builder: DecisionBuilder
    task_id: str
    step_id: str
    step_name: str


@dataclass(slots=True)
class DataMakeRunnerPorts:
    """
    `DataMakeRunnerPorts`（Runner 应用端口集合）。

    这里的“端口”指的是 Runner 需要外部系统提供的稳定能力边界，
    而不是某个具体类的内部实现细节。

    设计意图：
    - Runner 只依赖“要做什么”，不依赖“谁来做、怎么做”
    - 后续无论是替换 coordinator、service，还是把 callback 收敛成对象方法，
      只要端口语义不变，Runner 本身就不用改
    """

    dispatcher: Any
    ledger_repository: Any
    tracer: Tracer
    max_iterations: int
    consume_pending_replies: Callable[
        [AgentContext],
        Awaitable[tuple[bool, dict[str, Any] | None]],
    ]
    persist_flow_draft_if_present: Callable[[AgentContext], Awaitable[None]]
    recover_waiting_state: Callable[[AgentContext], Awaitable[dict[str, Any] | None]]
    get_next_action_decision: Callable[
        [str, dict[str, Any], AgentContext, str, str, int],
        Awaitable[NextActionDecision],
    ]
    hydrate_internal_decision_state: Callable[[NextActionDecision, AgentContext], None]


@dataclass(slots=True)
class DataMakeRunnerHooks:
    """
    `DataMakeRunnerHooks`（Runner 横切 Hook 集合）。

    这组对象只承载横切输出能力：
    - trace
    - waiting/final/error 结果组装

    它们不是业务应用端口，因为不会推进业务，只负责观测与呈现。
    """

    trace_decision_output: Callable[[str, NextActionDecision, int], Awaitable[None]]
    trace_paused_result: Callable[..., Awaitable[None]]
    trace_final_result: Callable[..., Awaitable[None]]
    trace_error_result: Callable[..., Awaitable[None]]
    build_waiting_user_result: Callable[..., dict[str, Any]]
    build_waiting_human_result: Callable[..., dict[str, Any]]


@dataclass(slots=True)
class DataMakeRunResult:
    """
    `DataMakeRunResult`（Runner 运行结果）。

    当前它仍然保持“薄包装”：
    - `kind` 表示 Runner 以哪种生命周期状态结束
    - `payload` 保持对外返回结构，兼容现有 Pattern / API / 测试

    后续若要继续演进，可以在不破坏外部 payload 兼容性的前提下，
    逐步把更多结构化字段从 payload 中提升出来。
    """

    kind: Literal["final", "waiting_user", "waiting_human", "error"]
    payload: dict[str, Any]

    def to_response_payload(self) -> dict[str, Any]:
        """
        输出兼容当前 Pattern 对外契约的结果字典。
        """

        return dict(self.payload)


class DataMakeDecisionRunner:
    """
    `DataMakeDecisionRunner`（datamake 决策循环执行器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 `DataMakeReActPattern` 入口壳之下，
      承接真正的“按轮决策 -> 分发 -> 回流”循环

    设计重点：
    - 只迁出主循环，不改变当前控制律
    - 把输入、应用端口、横切 Hook、运行结果显式分开
    - 后续若要继续抽象，可在这套结构上自然长成更稳定的 Runner API
    """

    def __init__(
        self,
        *,
        ports: DataMakeRunnerPorts,
        hooks: DataMakeRunnerHooks,
    ) -> None:
        self.ports = ports
        self.hooks = hooks

    async def run(
        self,
        run_input: DataMakeRunInput,
    ) -> DataMakeRunResult:
        """
        执行 datamake 主循环。

        这里仍然保持当前行为模型不变：
        - pending reply 优先消费
        - 没有新回复时尝试恢复 waiting state
        - 正常情况下构建 round context -> 生成 decision -> dispatch
        - waiting/final 结果直接返回，observation 继续下一轮
        """

        consecutive_failures = 0
        max_consecutive_failures = 5
        task = run_input.task
        context = run_input.context
        decision_builder = run_input.decision_builder
        task_id = run_input.task_id
        step_id = run_input.step_id
        step_name = run_input.step_name

        for _ in range(self.ports.max_iterations):
            handled_pending, early_result = await self.ports.consume_pending_replies(
                context
            )
            if early_result is not None:
                await self.hooks.trace_paused_result(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=step_name,
                    result=early_result,
                )
                return DataMakeRunResult(kind=str(early_result["status"]), payload=early_result)

            await self.ports.persist_flow_draft_if_present(context)

            recovered_waiting = None
            if not handled_pending:
                recovered_waiting = await self.ports.recover_waiting_state(context)
            if recovered_waiting is not None:
                await self.hooks.trace_paused_result(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=step_name,
                    result=recovered_waiting,
                    recovered=True,
                )
                return DataMakeRunResult(
                    kind=str(recovered_waiting["status"]),
                    payload=recovered_waiting,
                )

            round_context = await decision_builder.build_round_context(task, context)
            round_id = int(round_context["ledger_snapshot"]["next_round_id"])

            try:
                decision = await self.ports.get_next_action_decision(
                    task,
                    round_context,
                    context,
                    task_id,
                    step_id,
                    round_id,
                )
            except LLMNotAvailableError:
                raise
            except Exception as exc:
                consecutive_failures += 1
                await self._trace_round_failure(
                    task_id=task_id,
                    step_id=step_id,
                    round_id=round_id,
                    error_type=type(exc).__name__,
                    error_message=f"Round {round_id} 决策失败: {str(exc)}",
                    retryable=consecutive_failures < max_consecutive_failures,
                    attempt=consecutive_failures,
                )
                if consecutive_failures >= max_consecutive_failures:
                    return await self._build_and_trace_error_result(
                        task_id=task_id,
                        step_id=step_id,
                        step_name=step_name,
                        consecutive_failures=consecutive_failures,
                        latest_error=str(exc),
                        prefix="模型服务连续",
                        suffix="请稍后重试，或联系管理员检查模型服务状态。",
                    )
                await asyncio.sleep(2)
                continue

            consecutive_failures = 0

            # 必须在 append_decision 前注入系统内部态，否则账本无法回放授权事实。
            self.ports.hydrate_internal_decision_state(decision, context)
            await self.hooks.trace_decision_output(task_id, decision, round_id)
            await self.ports.ledger_repository.append_decision(
                task_id=context.task_id,
                round_id=round_id,
                decision=decision,
            )

            try:
                dispatch_outcome = await self.ports.dispatcher.dispatch(
                    task_id=context.task_id,
                    session_id=context.session_id,
                    round_id=round_id,
                    decision=decision,
                )
            except Exception as exc:
                consecutive_failures += 1
                await self._trace_round_failure(
                    task_id=task_id,
                    step_id=step_id,
                    round_id=round_id,
                    error_type=type(exc).__name__,
                    error_message=f"Round {round_id} 分发失败: {str(exc)}",
                    retryable=consecutive_failures < max_consecutive_failures,
                    attempt=consecutive_failures,
                    action=decision.action,
                )
                if consecutive_failures >= max_consecutive_failures:
                    return await self._build_and_trace_error_result(
                        task_id=task_id,
                        step_id=step_id,
                        step_name=step_name,
                        consecutive_failures=consecutive_failures,
                        latest_error=str(exc),
                        prefix="动作执行连续",
                        suffix="请稍后重试，或联系管理员检查服务状态。",
                    )
                await asyncio.sleep(2)
                continue

            if dispatch_outcome.kind == "final":
                payload = dispatch_outcome.payload
                payload.setdefault("iterations", round_id)
                await self.hooks.trace_final_result(
                    task_id=task_id,
                    step_id=step_id,
                    step_name=step_name,
                    payload=payload,
                    iterations=round_id,
                )
                return DataMakeRunResult(kind="final", payload=payload)

            if dispatch_outcome.kind == "observation":
                observation = dispatch_outcome.payload["observation"]
                await self.ports.ledger_repository.append_observation(
                    task_id=context.task_id,
                    round_id=round_id,
                    observation=observation,
                )
                continue

            if dispatch_outcome.kind == "waiting_user":
                return await self._handle_waiting_user(
                    task_id=task_id,
                    context=context,
                    round_id=round_id,
                    step_id=step_id,
                    step_name=step_name,
                    payload=dispatch_outcome.payload,
                )

            if dispatch_outcome.kind == "waiting_human":
                return await self._handle_waiting_human(
                    task_id=task_id,
                    context=context,
                    round_id=round_id,
                    step_id=step_id,
                    step_name=step_name,
                    payload=dispatch_outcome.payload,
                )

        await trace_error(
            self.ports.tracer,
            task_id,
            step_id,
            error_type="MaxIterationsError",
            error_message=f"造数智能体运行已超过最大迭代次数 {self.ports.max_iterations}",
            data={
                "pattern": "DataMakeReAct",
                "task": task[:200],
                "max_iterations": self.ports.max_iterations,
            },
        )
        raise MaxIterationsError(
            pattern_name="DataMakeReAct",
            max_iterations=self.ports.max_iterations,
            final_state="未在最大轮次内结束",
            context={
                "task": task[:200],
                "_already_traced": True,
            },
        )

    async def _trace_round_failure(
        self,
        *,
        task_id: str,
        step_id: str,
        round_id: int,
        error_type: str,
        error_message: str,
        retryable: bool,
        attempt: int,
        action: str | None = None,
    ) -> None:
        """
        记录单轮决策/分发失败。

        这类失败属于“仍有机会在下一轮自动重试”的运行中错误，
        因此只记 trace，不立即让主循环终止。
        """

        payload = {
            "round_id": round_id,
            "retryable": retryable,
            "attempt": attempt,
        }
        if action is not None:
            payload["action"] = action
        await trace_error(
            self.ports.tracer,
            task_id,
            step_id,
            error_type=error_type,
            error_message=error_message,
            data=payload,
        )

    async def _build_and_trace_error_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        consecutive_failures: int,
        latest_error: str,
        prefix: str,
        suffix: str,
    ) -> DataMakeRunResult:
        """
        当连续失败超过上限时，返回统一的友好错误结果。

        这里仍然沿用当前设计：返回一个 `need_user_input=True` 的 error payload，
        让外部调用方知道系统已停止自动重试，需要人工介入。
        """

        error_result = {
            "success": False,
            "status": "error",
            "need_user_input": True,
            "question": (
                f"{prefix} {consecutive_failures} 次失败，"
                f"最近错误：{latest_error[:200]}。\n"
                f"{suffix}"
            ),
            "field": "datamake_retry_confirm",
            "error_type": "ConsecutiveFailureExceeded",
        }
        await self.hooks.trace_error_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            result=error_result,
            consecutive_failures=consecutive_failures,
        )
        return DataMakeRunResult(kind="error", payload=error_result)

    async def _handle_waiting_user(
        self,
        *,
        task_id: str,
        context: AgentContext,
        round_id: int,
        step_id: str,
        step_name: str,
        payload: dict[str, Any],
    ) -> DataMakeRunResult:
        """
        持久化 waiting_user 结果，并组装 Pattern 对外返回结构。
        """

        ticket: InteractionTicket = payload["ticket"]
        pause_observation: ObservationEnvelope = payload["pause_observation"]
        await self.ports.ledger_repository.append_ticket(
            task_id=context.task_id,
            round_id=round_id,
            ticket=ticket,
        )
        await self.ports.ledger_repository.append_observation(
            task_id=context.task_id,
            round_id=round_id,
            observation=pause_observation,
        )
        result = self.hooks.build_waiting_user_result(
            question=payload["question"],
            field=payload["field"],
            chat_payload=payload["chat_payload"],
            ticket_id=ticket.ticket_id,
        )
        await self.hooks.trace_paused_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            result=result,
        )
        return DataMakeRunResult(kind="waiting_user", payload=result)

    async def _handle_waiting_human(
        self,
        *,
        task_id: str,
        context: AgentContext,
        round_id: int,
        step_id: str,
        step_name: str,
        payload: dict[str, Any],
    ) -> DataMakeRunResult:
        """
        持久化 waiting_human 结果，并组装 Pattern 对外返回结构。
        """

        ticket = payload["ticket"]
        pause_observation = payload["pause_observation"]
        await self.ports.ledger_repository.append_ticket(
            task_id=context.task_id,
            round_id=round_id,
            ticket=ticket,
        )
        await self.ports.ledger_repository.append_observation(
            task_id=context.task_id,
            round_id=round_id,
            observation=pause_observation,
        )
        result = self.hooks.build_waiting_human_result(
            question=payload["question"],
            field=payload["field"],
            chat_payload=payload["chat_payload"],
            approval_id=ticket.approval_id,
        )
        await self.hooks.trace_paused_result(
            task_id=task_id,
            step_id=step_id,
            step_name=step_name,
            result=result,
        )
        return DataMakeRunResult(kind="waiting_human", payload=result)
