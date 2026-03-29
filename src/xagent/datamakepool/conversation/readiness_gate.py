"""FlowDraft readiness gate。

这层的目标不是替代最终执行器，而是把“草稿现在是否足够进入下一阶段”
变成稳定、可解释、可测试的客观判定。

当前首版围绕 6 条条件做判断：
1. 至少存在一个步骤
2. 每个步骤都有 executor_type
3. 每个步骤的依赖都能在草稿内闭合
4. 所有必填参数都已 ready
5. 所有必填映射都已 ready
6. 不存在被标记为 blocked 的步骤 / 参数 / 映射

判定结果分三档：
- blocked：存在明确阻塞，必须先修订
- probe_ready：结构已经闭合，可以进入 probe
- execute_ready：probe 已经把步骤推进到可执行状态
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReadinessResult:
    """Readiness gate 的结构化输出。"""

    ready: bool
    status: str
    score: int
    blockers: list[str]
    checks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "score": self.score,
            "blockers": list(self.blockers),
            "checks": list(self.checks),
        }


class FlowDraftReadinessGate:
    """基于步骤 / 参数 / 映射状态计算草稿 readiness。"""

    def evaluate(self, draft: Any) -> ReadinessResult:
        steps = list(getattr(draft, "step_rows", []) or [])
        params = list(getattr(draft, "param_rows", []) or [])
        mappings = list(getattr(draft, "mapping_rows", []) or [])

        step_keys = {str(step.step_key) for step in steps}
        blockers: list[str] = []
        checks: list[dict[str, Any]] = []

        def record(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})
            if not ok:
                blockers.append(detail)

        record(
            "has_steps",
            bool(steps),
            "草稿中还没有任何可执行步骤" if not steps else f"已定义 {len(steps)} 个步骤",
        )

        missing_executor = [str(step.step_key) for step in steps if not str(step.executor_type or "").strip()]
        record(
            "step_executor_declared",
            not missing_executor,
            "以下步骤缺少 executor_type：" + "、".join(missing_executor)
            if missing_executor
            else "所有步骤都声明了 executor_type",
        )

        broken_dependencies: list[str] = []
        for step in steps:
            for dependency in list(step.dependencies or []):
                if str(dependency) not in step_keys:
                    broken_dependencies.append(f"{step.step_key}->{dependency}")
        record(
            "dependencies_closed",
            not broken_dependencies,
            "以下步骤依赖未闭合：" + "、".join(broken_dependencies)
            if broken_dependencies
            else "步骤依赖已闭合",
        )

        missing_required_params = [
            str(param.param_key)
            for param in params
            if bool(param.required) and str(param.status or "") != "ready"
        ]
        record(
            "required_params_ready",
            not missing_required_params,
            "以下必填参数尚未 ready：" + "、".join(missing_required_params)
            if missing_required_params
            else "必填参数均已 ready",
        )

        missing_required_mappings = [
            f"{mapping.target_step_key}.{mapping.target_field}"
            for mapping in mappings
            if bool(mapping.required) and str(mapping.status or "") != "ready"
        ]
        record(
            "required_mappings_ready",
            not missing_required_mappings,
            "以下必填映射尚未 ready：" + "、".join(missing_required_mappings)
            if missing_required_mappings
            else "必填映射均已 ready",
        )

        blocked_entities: list[str] = []
        blocked_entities.extend(
            f"step:{step.step_key}" for step in steps if str(step.status or "") == "blocked"
        )
        blocked_entities.extend(
            f"param:{param.param_key}" for param in params if str(param.status or "") == "blocked"
        )
        blocked_entities.extend(
            f"mapping:{mapping.target_step_key}.{mapping.target_field}"
            for mapping in mappings
            if str(mapping.status or "") == "blocked"
        )
        record(
            "no_blocked_entities",
            not blocked_entities,
            "存在阻塞对象：" + "、".join(blocked_entities)
            if blocked_entities
            else "当前没有被标记为 blocked 的对象",
        )

        passed = sum(1 for item in checks if item["ok"])
        score = int((passed / len(checks)) * 100) if checks else 0

        if blockers:
            return ReadinessResult(
                ready=False,
                status="blocked",
                score=score,
                blockers=blockers,
                checks=checks,
            )

        execute_ready = bool(steps) and all(
            str(step.status or "") in {"probe_ready", "execute_ready"}
            for step in steps
        )
        return ReadinessResult(
            ready=execute_ready,
            status="execute_ready" if execute_ready else "probe_ready",
            score=score,
            blockers=[],
            checks=checks,
        )
