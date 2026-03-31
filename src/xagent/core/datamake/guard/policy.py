"""
`Guard Policies`（护栏策略）集合模块。
"""

from __future__ import annotations

from ..contracts.decision import NextActionDecision
from ..resources.registry import ResourceActionDefinition


class RiskPolicy:
    """
    `RiskPolicy`（风险评估策略）。
    """

    _RISK_ORDER = {
        "low": 0,
        "medium": 1,
        "high": 2,
        "critical": 3,
    }

    def evaluate_risk(
        self,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
    ) -> str:
        """
        结合决策自评和资源注册元数据，给出最终风险等级。
        """

        action_risk = self._normalize_risk_level(action.risk_level)
        resource_risk = self._normalize_risk_level(resource_action.risk_level)

        # 风险合并遵循“取更高等级”而不是“资源定义直接覆盖”。
        # 这样资源显式标高风险时能升级，而主脑自评为高风险时也不会被默认 low 降级。
        if self._risk_score(resource_risk) >= self._risk_score(action_risk):
            return resource_risk
        return action_risk

    def merge_risk_levels(self, *risk_levels: str | None) -> str:
        """
        合并多个风险等级，返回其中最高等级。

        这个方法主要给 Guard 在叠加静态 SQL 校验风险、资源定义风险、
        主脑自评风险时使用，避免在多个模块里重复维护一套风险顺序表。
        """

        normalized_levels = [
            self._normalize_risk_level(risk_level) for risk_level in risk_levels
        ]
        if not normalized_levels:
            return "low"
        return max(normalized_levels, key=self._risk_score)

    def _normalize_risk_level(self, risk_level: str | None) -> str:
        """
        统一清洗风险等级文本，未知值回退为 low。
        """

        normalized = str(risk_level or "low").strip().lower()
        if normalized in self._RISK_ORDER:
            return normalized
        return "low"

    def _risk_score(self, risk_level: str) -> int:
        """
        把风险等级映射成可比较的顺序值。
        """

        return self._RISK_ORDER.get(risk_level, self._RISK_ORDER["low"])


class ApprovalPolicy:
    """
    `ApprovalPolicy`（审批要求策略）。
    """

    def requires_approval(
        self,
        action: NextActionDecision,
        resource_action: ResourceActionDefinition,
    ) -> bool:
        """
        判断动作是否需要人工确认。
        """

        approval_key = action.params.get("approval_key")
        approved_grants = action.params.get("_system_approval_grants", [])
        if (
            isinstance(approval_key, str)
            and isinstance(approved_grants, list)
            and approval_key in approved_grants
        ):
            return False

        return bool(action.requires_approval or resource_action.requires_approval)
