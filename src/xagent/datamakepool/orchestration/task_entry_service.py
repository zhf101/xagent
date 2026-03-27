"""Datamakepool 历史入口兼容服务。

当前主链路已经由 websocket + gateway + planner 驱动，但历史测试仍依赖
`TaskEntryService` 这个薄入口。这里保留一个最小可用实现，把分类、模板命中、
agent 回退三种路径串起来，保证旧入口语义仍然可验证。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from ..interpreter.intent_classifier import IntentClassifier, IntentType
from ..interpreter.intent_service import IntentService


@dataclass(frozen=True)
class TaskEntryResult:
    """旧入口处理结果。"""

    path: str
    agent_result: dict[str, Any] | None = None
    matched_template: dict[str, Any] | None = None
    template_run: dict[str, Any] | None = None


class TaskEntryService:
    """兼容旧入口语义的任务编排薄层。"""

    def __init__(
        self,
        *,
        intent_classifier: IntentClassifier,
        intent_service: IntentService,
        template_candidates_loader: Callable[[], list[dict[str, Any]]] | None = None,
        template_run_executor: Any | None = None,
    ):
        self._intent_classifier = intent_classifier
        self._intent_service = intent_service
        self._template_candidates_loader = template_candidates_loader or (lambda: [])
        self._template_run_executor = template_run_executor

    async def handle(
        self,
        user_input: str,
        *,
        task_id: int | None = None,
        created_by: int | None = None,
    ) -> TaskEntryResult:
        """处理用户输入并返回旧入口期望的路径结果。"""

        classification = await self._intent_classifier.classify(user_input)
        if classification.intent_type in {
            IntentType.GENERAL,
            IntentType.DATA_CONSULTATION,
        }:
            return TaskEntryResult(
                path="xagent_passthrough",
                agent_result={"reason": "agent_service_not_wired"},
            )

        candidates = self._template_candidates_loader()
        intent = self._intent_service.interpret(user_input, candidates)
        if (
            intent.template_match.is_full_match
            and self._template_run_executor is not None
        ):
            run_result = self._template_run_executor.execute(
                intent,
                task_id,
                created_by=created_by,
            )
            matched = intent.template_match.matched_template
            return TaskEntryResult(
                path="template_run",
                matched_template=(
                    {
                        "id": matched.template_id,
                        "name": matched.template_name,
                        "version": matched.version,
                        "system_short": matched.system_short,
                    }
                    if matched is not None
                    else None
                ),
                template_run=(
                    asdict(run_result)
                    if hasattr(run_result, "__dataclass_fields__")
                    else None
                ),
            )

        return TaskEntryResult(path="agent_generated_run")
