"""Datamakepool 旧入口兼容用意图分类器。

当前主链路已经由 task mode + gateway 承担模式路由，但历史测试和部分薄层
入口仍然依赖 `IntentClassifier`。这里保留一个轻量兼容实现，避免老入口彻底失效。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class IntentType(str, Enum):
    """任务意图枚举。"""

    GENERAL = "general"
    DATA_GENERATION = "data_generation"
    DATA_CONSULTATION = "data_consultation"


@dataclass(frozen=True)
class ClassificationResult:
    """意图分类结果。"""

    intent_type: IntentType
    confidence: float
    source: str


class IntentClassifier:
    """兼容旧测试与入口服务的轻量意图分类器。"""

    def __init__(self, llm: Any | None, llm_confidence_threshold: float = 0.5):
        self._llm = llm
        self._llm_confidence_threshold = llm_confidence_threshold

    async def classify(self, user_input: str) -> ClassificationResult:
        """对输入做三态意图判定。

        策略顺序：
        1. 规则层先做明显短路，保证高确定性场景不浪费 LLM 调用
        2. 规则不确定时再回退给 LLM
        3. 无 LLM 或 LLM 低置信度时，保守降级到 `GENERAL`
        """

        normalized = str(user_input or "").strip().lower()

        rule_result = self._classify_by_rule(normalized)
        if rule_result is not None:
            return rule_result

        if self._llm is None:
            return ClassificationResult(
                intent_type=IntentType.GENERAL,
                confidence=0.0,
                source="llm",
            )

        raw_result = await self._llm.classify(user_input)
        intent_name = str(raw_result.get("intent_type") or "general")
        try:
            intent_type = IntentType(intent_name)
        except ValueError:
            intent_type = IntentType.GENERAL
        confidence = float(raw_result.get("confidence") or 0.0)
        if confidence < self._llm_confidence_threshold:
            return ClassificationResult(
                intent_type=IntentType.GENERAL,
                confidence=confidence,
                source="llm",
            )

        return ClassificationResult(
            intent_type=intent_type,
            confidence=confidence,
            source="llm",
        )

    def _classify_by_rule(self, normalized: str) -> ClassificationResult | None:
        """规则层只处理高确定性语句，避免误杀模糊输入。"""

        generation_keywords = ("造数", "造 ", "生成测试数据", "造一批", "生成一批")
        consultation_keywords = ("支持哪些", "支持什么", "造数平台", "有哪些数据库")
        general_keywords = ("正则", "regex", "python", "代码", "脚本")

        if any(keyword in normalized for keyword in consultation_keywords):
            return ClassificationResult(
                intent_type=IntentType.DATA_CONSULTATION,
                confidence=0.9,
                source="rule",
            )

        if any(keyword in normalized for keyword in generation_keywords):
            return ClassificationResult(
                intent_type=IntentType.DATA_GENERATION,
                confidence=0.95,
                source="rule",
            )

        if any(keyword in normalized for keyword in general_keywords):
            return ClassificationResult(
                intent_type=IntentType.GENERAL,
                confidence=0.9,
                source="rule",
            )

        return None
