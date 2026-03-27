"""Task mode execution gateway for datamakepool V3.

本模块只负责“读取 task 上的 domain_mode 并输出执行入口决策”，
不直接承担模板匹配或 orchestrator 注册逻辑。这样可以把：

- Task 创建时的 mode 持久化
- websocket 执行前的模式分流

与后续更复杂的模板执行 / orchestrator 切换解耦。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, cast


DomainMode = Literal["data_generation", "data_consultation", "general"]

_DATAMAKEPOOL_KNOWLEDGE = (
    "你当前处于智能造数平台的知识问答模式。"
    "当用户询问造数能力、模板、资产类型、审批规则、运行路径时，"
    "应基于造数平台领域知识进行解释。"
)


@dataclass(frozen=True)
class TaskModeDecision:
    """Task 执行前的模式决策结果。"""

    domain_mode: DomainMode
    execution_context: Dict[str, Any]
    route_to_orchestrator: bool = False


class DatamakepoolTaskModeGateway:
    """根据 task.agent_config.domain_mode 决定执行模式。"""

    @staticmethod
    def resolve_domain_mode(task: Any) -> DomainMode:
        """从 task.agent_config 中解析 domain_mode。

        解析失败时统一回退为 `general`，避免脏数据把执行入口打挂。
        """

        agent_config = getattr(task, "agent_config", None)
        if not isinstance(agent_config, dict):
            return "general"

        raw = agent_config.get("domain_mode")
        if not isinstance(raw, str):
            return "general"

        normalized = raw.strip().lower()
        if normalized in {"data_generation", "data_consultation", "general"}:
            return cast(DomainMode, normalized)
        return "general"

    @classmethod
    def build_decision(
        cls,
        task: Any,
        base_context: Dict[str, Any] | None = None,
    ) -> TaskModeDecision:
        """根据 task 模式构造执行前上下文。

        这里只做最轻量的模式分流，不承担模板匹配和 orchestrator 规划。
        """

        mode = cls.resolve_domain_mode(task)
        context: Dict[str, Any] = dict(base_context or {})

        if mode == "data_consultation":
            context["domain_mode"] = mode
            context["datamakepool_knowledge"] = _DATAMAKEPOOL_KNOWLEDGE
        elif mode == "data_generation":
            # 当前阶段仅显式标记模式，为后续模板匹配和 orchestrator 切换做准备。
            context["domain_mode"] = mode

        return TaskModeDecision(domain_mode=mode, execution_context=context)

    @staticmethod
    def should_route_to_orchestrator(
        domain_mode: DomainMode, template_match_result: Any | None
    ) -> bool:
        """判断当前请求是否应该切到 datamakepool orchestrator。"""

        if domain_mode != "data_generation":
            return False

        if template_match_result is None:
            return True

        match_type = getattr(template_match_result, "match_type", None)
        if isinstance(match_type, str):
            return match_type in {"partial_match", "no_match"}

        matched_template = getattr(template_match_result, "matched_template", None)
        return matched_template is None
