"""
`Pattern Hook Adapter`（Pattern Hook 适配器）模块。

这个模块负责承接 datamake 主循环里“和业务决策本身无关，但又必须稳定输出”的横切能力。

当前首版只收口两类最常见横切逻辑：
- trace / task end / completion 的统一出入口
- waiting_user / waiting_human / error / final 的对外结果组装

明确不负责：
- 不决定下一轮业务动作
- 不修改 observation / decision 的事实语义
- 不推进任何隐藏状态机
"""

from __future__ import annotations

import json
from typing import Any

from ...agent.trace import (
    TraceCategory,
    Tracer,
    trace_ai_message,
    trace_error,
    trace_task_start,
    trace_task_completion,
    trace_task_end,
    trace_user_message,
)
from ..contracts.decision import NextActionDecision


class PatternHookAdapter:
    """
    `PatternHookAdapter`（Pattern Hook 适配器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 Pattern / Runner 两侧，负责处理横切输出

    当前职责：
    - 把 trace 记录逻辑从主循环细节中抽离
    - 统一 waiting/final/error 的外部返回结构
    - 为后续 progress hook / WebSocket hook 继续扩展预留稳定挂点
    """

    def __init__(self, *, tracer: Tracer) -> None:
        self.tracer = tracer

    def build_waiting_user_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        ticket_id: str,
    ) -> dict[str, Any]:
        """
        组装 `waiting_user` 的对外返回结构。
        """

        return {
            "success": True,
            "status": "waiting_user",
            "need_user_input": True,
            "question": question,
            "field": field,
            "chat_response": chat_payload,
            "ticket_id": ticket_id,
        }

    def build_waiting_human_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        approval_id: str,
    ) -> dict[str, Any]:
        """
        组装 `waiting_human` 的对外返回结构。
        """

        return {
            "success": True,
            "status": "waiting_human",
            "need_user_input": True,
            "question": question,
            "field": field,
            "chat_response": chat_payload,
            "approval_id": approval_id,
        }

    def build_recovered_waiting_user_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        ticket_id: str,
        resume_token: str,
    ) -> dict[str, Any]:
        """
        组装“从持久化 pending 状态恢复出来”的 `waiting_user` 返回结构。
        """

        result = self.build_waiting_user_result(
            question=question,
            field=field,
            chat_payload=chat_payload,
            ticket_id=ticket_id,
        )
        result["resume_token"] = resume_token
        return result

    def build_recovered_waiting_human_result(
        self,
        *,
        question: str,
        field: str,
        chat_payload: dict[str, Any],
        approval_id: str,
        resume_token: str,
    ) -> dict[str, Any]:
        """
        组装“从持久化 pending 状态恢复出来”的 `waiting_human` 返回结构。
        """

        result = self.build_waiting_human_result(
            question=question,
            field=field,
            chat_payload=chat_payload,
            approval_id=approval_id,
        )
        result["resume_token"] = resume_token
        return result

    def resolve_trace_step_context(self, task_id: str) -> tuple[str, str]:
        """
        为当前 datamake run 生成稳定的 step 上下文。

        这里仍然维持“同一个 Pattern 实例在当前任务周期内复用同一 step_id”的行为，
        目的是避免 trace 侧看到多条其实属于同一个主循环的碎片 step。
        """

        step_id = getattr(self, "_current_step_id", None) or f"{task_id}_main"
        step_name = getattr(self, "_current_step_name", None) or "main"
        self._current_step_id = step_id
        self._current_step_name = step_name
        return step_id, step_name

    def build_user_trace_data(
        self,
        *,
        task: str,
        tools: list[Any],
        step_id: str,
        step_name: str,
        file_info: Any,
        uploaded_files: Any,
    ) -> dict[str, Any]:
        """
        组装任务级用户输入 trace 数据。

        这里属于 run-start 的横切观测内容，不是业务决策证据，
        因此和 waiting/final/error 一样收口在 hook 适配层。
        """

        return {
            "pattern": "DataMakeReAct",
            "task": task[:200],
            "tools": [tool.metadata.name for tool in tools],
            "step_id": step_id,
            "step_name": step_name,
            "file_info": file_info,
            "uploaded_files": uploaded_files,
        }

    async def trace_run_start(
        self,
        *,
        task_id: str,
        task: str,
        max_iterations: int,
        tools: list[Any],
        step_id: str,
        step_name: str,
        file_info: Any,
        uploaded_files: Any,
    ) -> None:
        """
        记录一次 datamake run 的开始事件。

        这里把 `task_start_message + task_start_react` 成对发出，
        目的是让入口壳只负责调用，不再自己拼 trace payload。
        """

        await trace_user_message(
            self.tracer,
            task_id,
            task,
            data=self.build_user_trace_data(
                task=task,
                tools=tools,
                step_id=step_id,
                step_name=step_name,
                file_info=file_info,
                uploaded_files=uploaded_files,
            ),
        )
        await trace_task_start(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "pattern": "DataMakeReAct",
                "task": task[:200],
                "max_iterations": max_iterations,
                "tools": [tool.metadata.name for tool in tools],
                "step_id": step_id,
                "step_name": step_name,
            },
        )

    async def trace_decision_output(
        self,
        task_id: str,
        decision: NextActionDecision,
        round_id: int,
    ) -> None:
        """
        记录当前轮 AI 决策输出。
        """

        await trace_ai_message(
            self.tracer,
            task_id,
            message=json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
            data={
                "decision_mode": decision.decision_mode,
                "action_kind": decision.action_kind,
                "action": decision.action,
                "round_id": round_id,
            },
        )

    async def trace_run_result(self, task_id: str, result: dict[str, Any]) -> None:
        """
        记录一次 run 返回给外部调用方的结果摘要。
        """

        message = None
        for key in ("output", "question", "final_message"):
            value = result.get(key)
            if value not in (None, ""):
                message = str(value)
                break
        if message is None:
            message = json.dumps(result, ensure_ascii=False, default=str)
        await trace_ai_message(
            self.tracer,
            task_id,
            message=message,
            data={
                "status": result.get("status"),
                "success": result.get("success"),
            },
        )

    async def trace_paused_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        result: dict[str, Any],
        recovered: bool = False,
    ) -> None:
        """
        记录等待态返回。

        waiting_user / waiting_human 本质上都是“当前 run 暂停并把控制权交回外部”，
        所以统一在这里做 trace 收口，避免 Runner 和 Pattern 各自拼一套 end payload。
        """

        await self.trace_run_result(task_id, result)
        await trace_task_end(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "status": result.get("status"),
                "paused": True,
                "step_id": step_id,
                "step_name": step_name,
                "recovered": recovered,
            },
        )

    async def trace_final_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        payload: dict[str, Any],
        iterations: int,
    ) -> None:
        """
        记录主循环成功/失败结束时的最终结果。
        """

        await self.trace_run_result(task_id, payload)
        await trace_task_completion(
            self.tracer,
            task_id,
            result=payload.get("output") or payload.get("final_message") or payload,
            success=bool(payload.get("success", False)),
        )
        await trace_task_end(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "status": payload.get("status"),
                "iterations": iterations,
                "success": payload.get("success"),
                "step_id": step_id,
                "step_name": step_name,
            },
        )

    async def trace_error_result(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        result: dict[str, Any],
        consecutive_failures: int,
    ) -> None:
        """
        记录连续失败超过阈值后的错误返回。
        """

        await self.trace_run_result(task_id, result)
        await trace_task_end(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "status": "error",
                "consecutive_failures": consecutive_failures,
                "step_id": step_id,
                "step_name": step_name,
            },
        )

    async def trace_pattern_failure(
        self,
        *,
        task_id: str,
        step_id: str,
        step_name: str,
        task: str,
        exc: Exception,
    ) -> None:
        """
        对统一异常边界做 trace 收口。
        """

        error_context = getattr(exc, "context", {}) if hasattr(exc, "context") else {}
        if not error_context.get("_already_traced"):
            await trace_error(
                self.tracer,
                task_id,
                step_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                data={
                    "pattern": "DataMakeReAct",
                    "task": task[:200],
                    "step_name": step_name,
                    "context": error_context,
                },
            )

        await trace_task_end(
            self.tracer,
            task_id,
            TraceCategory.REACT,
            data={
                "status": "failed",
                "success": False,
                "step_id": step_id,
                "step_name": step_name,
                "error_type": type(exc).__name__,
            },
        )
