"""FlowDraft -> Compiled DAG 编译器。

当前 runtime 还没有完全切到“任意 FlowDraft 直跑”模式，
因此这里先产出一个统一、稳定、可审计的 compiled payload，供：

- execute 入口消费
- agent/orchestrator 在 planning prompt 中复用
- 运行账本记录“本次执行基于哪一版草稿”

编译原则：
- 只基于子表，不直接信任 fact_snapshot
- 把参数值和映射关系投影到步骤输入上
- 保留 unresolved_mappings，避免假装编译成功
"""

from __future__ import annotations

from typing import Any

from .approval_projection import FlowDraftApprovalProjector


class FlowDraftPlanCompiler:
    """把结构化草稿编译成统一 DAG 载荷。"""

    def __init__(
        self,
        *,
        approval_projector: FlowDraftApprovalProjector | None = None,
    ) -> None:
        self._approval_projector = approval_projector or FlowDraftApprovalProjector()

    def compile(self, draft: Any) -> dict[str, Any]:
        approval_projection = self._approval_projector.project(draft)
        params = {str(row.param_key): row for row in list(getattr(draft, "param_rows", []) or [])}
        mappings = list(getattr(draft, "mapping_rows", []) or [])
        mapping_by_step: dict[str, list[Any]] = {}
        for mapping in mappings:
            mapping_by_step.setdefault(str(mapping.target_step_key), []).append(mapping)

        compiled_steps: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for step in list(getattr(draft, "step_rows", []) or []):
            input_data: dict[str, Any] = {}
            for mapping in mapping_by_step.get(str(step.step_key), []):
                value, resolved = self._resolve_mapping(mapping=mapping, params=params)
                if resolved:
                    input_data[str(mapping.target_field)] = value
                else:
                    unresolved.append(
                        {
                            "target_step_key": str(mapping.target_step_key),
                            "target_field": str(mapping.target_field),
                            "source_kind": str(mapping.source_kind or ""),
                            "source_ref": mapping.source_ref,
                            "status": str(mapping.status or ""),
                        }
                    )

            compiled_steps.append(
                {
                    "step_key": str(step.step_key),
                    "name": str(step.title or step.step_key),
                    "kind": str(step.executor_type or ""),
                    "target_ref": step.target_ref,
                    "status": str(step.status or ""),
                    "dependencies": list(step.dependencies or []),
                    "config": dict(step.config_payload or {}),
                    "input_data": input_data,
                    "output_contract": dict(step.output_contract or {}),
                    "approval": next(
                        (
                            item
                            for item in list(approval_projection.summary.get("items") or [])
                            if str(item.get("step_key") or "") == str(step.step_key)
                        ),
                        None,
                    ),
                }
            )

        param_snapshot: dict[str, Any] = {}
        for key, row in params.items():
            payload = row.value_payload
            if isinstance(payload, dict) and "value" in payload:
                param_snapshot[key] = payload.get("value")
            else:
                param_snapshot[key] = payload

        return {
            "draft_id": int(draft.id),
            "version": int(draft.version or 1),
            "goal_summary": str(getattr(draft, "goal_summary", "") or ""),
            "system_short": getattr(draft, "system_short", None),
            "status": str(getattr(draft, "status", "") or ""),
            "readiness_score": getattr(draft, "readiness_score", None),
            "blocking_reasons": list(getattr(draft, "blocking_reasons", []) or []),
            "source_candidate": {
                "type": getattr(draft, "source_candidate_type", None),
                "id": getattr(draft, "source_candidate_id", None),
            },
            "approval_summary": dict(approval_projection.summary or {}),
            "params": param_snapshot,
            "steps": compiled_steps,
            "unresolved_mappings": unresolved,
        }

    @staticmethod
    def _resolve_mapping(*, mapping: Any, params: dict[str, Any]) -> tuple[Any, bool]:
        source_kind = str(mapping.source_kind or "")
        if source_kind == "literal":
            return mapping.literal_value, True
        if source_kind == "draft_param":
            param = params.get(str(mapping.source_ref or ""))
            if param is None or str(param.status or "") != "ready":
                return None, False
            payload = param.value_payload
            if isinstance(payload, dict) and "value" in payload:
                return payload.get("value"), True
            return payload, payload is not None
        if source_kind == "step_output":
            # 当前首版 compiler 只保留引用，实际解析交给 runtime。
            source_ref = str(mapping.source_ref or "")
            source_path = str(mapping.source_path or "")
            if not source_ref:
                return None, False
            return {"$ref": f"steps.{source_ref}.{source_path or 'data'}"}, True
        return None, False
