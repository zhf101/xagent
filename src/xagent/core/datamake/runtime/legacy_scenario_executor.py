"""
`Legacy Scenario Executor`（历史场景执行器）模块。

这个执行器不是重新实现一套旧场景引擎，
而是把“历史造数场景模板调用”兼容桥接到已发布模板版本执行链路上。
"""

from __future__ import annotations

from typing import Any

from ..contracts.constants import RUNTIME_STATUS_FAILED
from ..contracts.runtime import RuntimeResult
from ..contracts.template_pipeline import CompiledDagStep


class LegacyScenarioExecutor:
    """
    `LegacyScenarioExecutor`（历史场景执行器）。

    设计边界：
    - 当前阶段只做“历史场景 -> 已发布模板版本”的兼容桥接。
    - 不重新定义 legacy_scenario 的独立执行协议，避免 runtime 里出现两套几乎重复的模板复跑逻辑。
    - 若未来真的接入老场景中心，也应只替换这个桥，而不是侵入主循环与 compiled DAG 调度器。
    """

    def __init__(self, *, template_version_executor: Any | None = None) -> None:
        self.template_version_executor = template_version_executor

    async def execute(
        self,
        *,
        step: CompiledDagStep,
        params: Any,
    ) -> RuntimeResult:
        """
        执行一个 legacy_scenario 步骤。

        当前兼容规则：
        - 优先读取 `legacy_template_snapshot / legacy_template_version_id`
        - 若没有，再兼容读取 `template_snapshot / template_version_id`
        - 最终统一委托给 `TemplateVersionExecutor`
        """

        if self.template_version_executor is None:
            return RuntimeResult(
                run_id=f"legacy_scenario_step_{step.step_key}",
                status=RUNTIME_STATUS_FAILED,
                summary="当前运行时未配置模板版本执行器，无法桥接历史场景",
                facts={"step_key": step.step_key, "kind": step.kind},
                error="legacy_scenario_template_version_executor_not_configured",
            )

        normalized_step = step.model_copy(
            update={
                "config": self._normalize_config(step.config),
            }
        )
        result = await self.template_version_executor.execute_from_step(
            step=normalized_step,
            params=params,
        )
        return result.model_copy(
            update={
                "artifact_type": "legacy_scenario",
                "artifact_ref": {
                    **dict(result.artifact_ref),
                    "legacy_step_key": step.step_key,
                    "bridge": "template_version",
                },
                "summary": (
                    "历史场景执行完成"
                    if result.status != RUNTIME_STATUS_FAILED
                    else "历史场景执行失败"
                ),
            }
        )

    def _normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        把 legacy_scenario 步骤的配置归一成模板版本执行器可识别的字段。

        这样 compiled DAG 调度层只知道“这里有个历史场景步骤”，
        真正的兼容细节收敛在本桥接器里。
        """

        normalized = dict(config)
        if "template_snapshot" not in normalized and isinstance(
            normalized.get("legacy_template_snapshot"),
            dict,
        ):
            normalized["template_snapshot"] = dict(normalized["legacy_template_snapshot"])
        if (
            "template_version_id" not in normalized
            and normalized.get("legacy_template_version_id") is not None
        ):
            normalized["template_version_id"] = normalized["legacy_template_version_id"]
        return normalized
