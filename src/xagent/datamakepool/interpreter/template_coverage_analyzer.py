"""模板覆盖度分析器。

`TemplateMatcher` 先回答“像不像这个模板”，
本模块进一步回答“这个模板能覆盖用户需求到什么程度”。

这是把 `full_match` 和 `partial_match` 区分开的关键层。
"""

from __future__ import annotations

import json
import re
from typing import Any


_REQUIREMENT_SPLIT_PATTERN = re.compile(
    r"(?:，|,|；|;|并且|同时|另外|还要|再|然后|以及|且| and )", re.IGNORECASE
)


class TemplateCoverageAnalyzer:
    """估算模板对用户需求的覆盖程度。"""

    def split_requirements(self, user_input: str) -> list[str]:
        """把自然语言请求粗粒度拆成多个 requirement。

        当前是基于连接词和标点的启发式拆分，目标是先支持可解释的多需求分析。
        """

        parts = [
            segment.strip()
            for segment in _REQUIREMENT_SPLIT_PATTERN.split(user_input)
            if segment and segment.strip()
        ]
        return parts or [user_input.strip()]

    def resolve_reusable_steps(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        """解析候选模板里的步骤定义。

        兼容历史上可能存在的 JSON 字符串形式，统一返回 list，降低上层分支复杂度。
        """

        raw_steps = candidate.get("step_spec") or []
        if isinstance(raw_steps, str):
            try:
                raw_steps = json.loads(raw_steps)
            except Exception:
                raw_steps = []
        return raw_steps if isinstance(raw_steps, list) else []

    def analyze(
        self,
        *,
        user_input: str,
        params: dict[str, Any],
        candidate: dict[str, Any],
        match_score: float,
    ) -> dict[str, Any]:
        """综合用户需求、候选模板和召回分，输出覆盖分析结果。

        返回值会被 `TemplateMatchResult` 直接消费，因此这里保持字典结构稳定。
        """

        requirements = self.split_requirements(user_input)
        if not requirements:
            requirements = [user_input.strip()]

        tags = [
            str(item).lower()
            for item in (candidate.get("tags") or [])
            if str(item).strip()
        ]
        candidate_system = str(candidate.get("system_short") or "").lower()
        system_short = str(params.get("system_short") or "").lower()

        # 先按 requirement 判断哪些需求已被模板显式覆盖。
        covered_requirements: list[str] = []
        missing_requirements: list[str] = []
        for requirement in requirements:
            requirement_lower = requirement.lower()
            matches_tag = any(tag and tag in requirement_lower for tag in tags)
            matches_system = bool(system_short) and (
                system_short in requirement_lower
                or (
                    len(requirements) == 1
                    and candidate_system == system_short
                )
            )
            if matches_tag or matches_system:
                covered_requirements.append(requirement)
            else:
                missing_requirements.append(requirement)

        # 如果一个 requirement 都没命中，至少保留首个 requirement 作为“弱覆盖”，
        # 避免高召回模板在完全空覆盖时仍然丢失上下文。
        if not covered_requirements and requirements:
            covered_requirements.append(requirements[0])
            missing_requirements = requirements[1:]

        # coverage_score 不是纯召回分，而是“模板像不像”与“需求覆盖率”的混合信号。
        total_requirements = max(len(requirements), 1)
        coverage_ratio = len(covered_requirements) / total_requirements
        coverage_score = min(1.0, round(match_score * 0.6 + coverage_ratio * 0.4, 4))

        if coverage_ratio >= 1.0 and coverage_score >= 0.72:
            match_type = "full_match"
        elif coverage_score >= 0.28 and covered_requirements:
            match_type = "partial_match"
        else:
            match_type = "no_match"

        return {
            "match_type": match_type,
            "coverage_score": coverage_score,
            "covered_requirements": covered_requirements,
            "missing_requirements": missing_requirements,
            "reusable_steps": self.resolve_reusable_steps(candidate),
        }
