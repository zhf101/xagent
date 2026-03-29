"""FlowDraft 持久化与收敛服务。

这一层负责把会话事实快照收敛成结构化的 FlowDraft：
- 主表保存版本、状态、compiled payload、readiness 快照
- 子表保存步骤 / 参数 / 映射

当前阶段的职责边界：
1. 基于会话事实构建或更新 active draft
2. 把 probe 结果补丁回 draft，而不是只写 session.fact_snapshot
3. 运行 readiness gate，并在可执行时生成 compiled DAG
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_conversation import DataMakepoolConversationSession
from xagent.web.models.datamakepool_flow_draft import DataMakepoolFlowDraft
from xagent.web.models.datamakepool_flow_draft_detail import (
    DataMakepoolFlowDraftMapping,
    DataMakepoolFlowDraftParam,
    DataMakepoolFlowDraftStep,
)

from .plan_compiler import FlowDraftPlanCompiler
from .readiness_gate import FlowDraftReadinessGate


class FlowDraftService:
    """FlowDraft 的 CRUD、收敛与状态转换。"""

    REQUIRED_PARAM_KEYS = (
        "target_system",
        "target_entity",
        "execution_method",
        "target_environment",
    )

    PARAM_LABELS = {
        "target_system": "目标系统",
        "target_entity": "目标表名或接口",
        "execution_method": "执行方式",
        "target_environment": "目标环境",
        "data_count": "数据量",
        "field_constraints": "字段约束 / 业务规则",
        "data_dependencies": "数据依赖",
        "reuse_strategy": "处理方式",
        "selected_candidate_id": "候选对象",
        "selected_source_type": "候选来源类型",
    }

    EXECUTOR_LABELS = {
        "sql": "SQL 造数",
        "http": "HTTP 接口造数",
        "dubbo": "Dubbo 服务造数",
        "template": "模板复用执行",
        "legacy_scenario": "存量场景复用",
        "auto": "自动选择执行路径",
    }

    ACTIVE_STATUSES = {"drafting", "blocked", "probe_ready", "compile_ready", "execute_ready"}

    def __init__(self, db: Session):
        self._db = db
        self._gate = FlowDraftReadinessGate()
        self._compiler = FlowDraftPlanCompiler()

    def create_draft(
        self,
        *,
        session_id: int,
        steps: list[dict[str, Any]],
        param_graph: dict[str, Any] | None = None,
        notes: str | None = None,
        goal_summary: str | None = None,
        system_short: str | None = None,
        source_candidate_type: str | None = None,
        source_candidate_id: str | None = None,
        params: list[dict[str, Any]] | None = None,
        mappings: list[dict[str, Any]] | None = None,
    ) -> DataMakepoolFlowDraft:
        """为会话创建新草稿，将旧 active draft 归档。"""

        latest = (
            self._db.query(DataMakepoolFlowDraft)
            .filter(DataMakepoolFlowDraft.session_id == session_id)
            .order_by(DataMakepoolFlowDraft.version.desc())
            .first()
        )
        next_version = (latest.version + 1) if latest else 1

        self._db.query(DataMakepoolFlowDraft).filter(
            DataMakepoolFlowDraft.session_id == session_id,
            DataMakepoolFlowDraft.status.in_(list(self.ACTIVE_STATUSES | {"superseded"})),
        ).update({"status": "archived"}, synchronize_session=False)

        draft = DataMakepoolFlowDraft(
            session_id=session_id,
            version=next_version,
            status="drafting",
            goal_summary=goal_summary,
            system_short=system_short,
            source_candidate_type=source_candidate_type,
            source_candidate_id=source_candidate_id,
            steps=steps,
            param_graph=param_graph,
            notes=notes,
        )
        self._db.add(draft)
        self._db.flush()
        self._sync_child_rows(
            draft=draft,
            steps=steps,
            params=params or [],
            mappings=mappings or [],
        )
        self._attach_to_session(session_id=session_id, draft_id=int(draft.id))
        self._db.commit()
        self._db.refresh(draft)
        return draft

    def get_active_draft(self, session_id: int) -> DataMakepoolFlowDraft | None:
        """返回会话当前 active 草稿。"""

        return (
            self._db.query(DataMakepoolFlowDraft)
            .filter(
                DataMakepoolFlowDraft.session_id == session_id,
                DataMakepoolFlowDraft.status.notin_(["archived", "superseded"]),
            )
            .order_by(DataMakepoolFlowDraft.version.desc())
            .first()
        )

    def get_draft_by_id(self, draft_id: int) -> DataMakepoolFlowDraft | None:
        return (
            self._db.query(DataMakepoolFlowDraft)
            .filter(DataMakepoolFlowDraft.id == draft_id)
            .first()
        )

    def export_fact_snapshot(
        self,
        draft: DataMakepoolFlowDraft | None,
        *,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把 FlowDraft 子表还原成当前轮次可消费的稳定事实快照。

        设计目的：
        - 让 ReAct / execution_context 优先读取 draft 的中间真相，而不是直接依赖 session.fact_snapshot
        - 对仍未迁移的旧字段保留 fallback，避免一次性打断现有链路
        """

        merged = dict(fallback or {})
        if draft is None:
            return merged

        for row in list(getattr(draft, "param_rows", []) or []):
            if str(row.status or "") == "blocked":
                continue
            payload = row.value_payload
            if isinstance(payload, dict) and "value" in payload:
                value = payload.get("value")
            else:
                value = payload
            if value not in (None, "", [], {}):
                merged[str(row.param_key)] = value

        if getattr(draft, "source_candidate_id", None):
            merged["selected_candidate_id"] = str(draft.source_candidate_id)
        if getattr(draft, "source_candidate_type", None):
            merged["selected_source_type"] = str(draft.source_candidate_type)
        if getattr(draft, "system_short", None) and not merged.get("target_system"):
            merged["target_system"] = str(draft.system_short)
        return merged

    def mark_probe_pending(self, draft_id: int) -> DataMakepoolFlowDraft | None:
        """兼容旧接口：当前同步 probe 不再有 pending，中间态统一记为 probe_ready。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None
        draft.status = "probe_ready"
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return draft

    def upsert_from_conversation(
        self,
        *,
        session_id: int,
        goal_summary: str,
        fact_snapshot: dict[str, Any],
        draft_patch: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> DataMakepoolFlowDraft:
        """根据当前会话事实构建或刷新 active draft。"""

        draft_patch = dict(draft_patch or {})
        source_candidate_id = self._normalize_text(fact_snapshot.get("selected_candidate_id"))
        source_candidate_type = self._normalize_text(fact_snapshot.get("selected_source_type"))
        system_short = self._normalize_text(fact_snapshot.get("target_system"))

        params = self._build_param_rows(fact_snapshot=fact_snapshot)
        steps = self._build_step_rows(
            fact_snapshot=fact_snapshot,
            source_candidate_type=source_candidate_type,
            source_candidate_id=source_candidate_id,
            draft_patch=draft_patch,
        )
        mappings = self._build_mapping_rows(steps=steps, params=params)
        param_graph = self._build_param_graph(mappings=mappings)

        active = self.get_active_draft(session_id)
        if active is None or self._should_rotate_version(
            draft=active,
            source_candidate_type=source_candidate_type,
            source_candidate_id=source_candidate_id,
        ):
            draft = self.create_draft(
                session_id=session_id,
                steps=steps,
                params=params,
                mappings=mappings,
                param_graph=param_graph,
                notes=notes,
                goal_summary=goal_summary,
                system_short=system_short,
                source_candidate_type=source_candidate_type,
                source_candidate_id=source_candidate_id,
            )
        else:
            draft = active
            self._merge_existing_step_state(draft=draft, steps=steps)
            self._merge_existing_param_state(draft=draft, params=params)
            self._merge_existing_mapping_state(draft=draft, mappings=mappings)
            draft.goal_summary = goal_summary
            draft.system_short = system_short
            draft.source_candidate_type = source_candidate_type
            draft.source_candidate_id = source_candidate_id
            draft.steps = steps
            draft.param_graph = param_graph
            if notes:
                draft.notes = notes
            self._sync_child_rows(
                draft=draft,
                steps=steps,
                params=params,
                mappings=mappings,
            )
            self._db.add(draft)
            self._db.commit()
            self._db.refresh(draft)

        return self.refresh_readiness(int(draft.id)) or draft

    def apply_probe_findings(
        self,
        draft_id: int,
        *,
        findings: list[dict[str, Any]],
        param_updates: list[dict[str, Any]] | None = None,
        mapping_updates: list[dict[str, Any]] | None = None,
        step_updates: list[dict[str, Any]] | None = None,
    ) -> DataMakepoolFlowDraft | None:
        """回写 probe 发现，并把结果补丁到 param/mapping/step。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None

        existing = list(draft.probe_findings or [])
        existing.extend(findings)
        draft.probe_findings = existing[-50:]

        self._apply_param_updates(draft=draft, updates=param_updates or [])
        self._apply_mapping_updates(draft=draft, updates=mapping_updates or [])
        self._apply_step_updates(draft=draft, updates=step_updates or [])
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return self.refresh_readiness(draft_id)

    def apply_readiness_verdict(
        self,
        draft_id: int,
        *,
        verdict: dict[str, Any],
    ) -> DataMakepoolFlowDraft | None:
        """写入 readiness 判定，必要时同步 compiled payload。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None

        blockers = list(verdict.get("blockers") or [])
        draft.readiness_verdict = dict(verdict)
        draft.readiness_score = (
            int(verdict.get("score"))
            if verdict.get("score") is not None
            else None
        )
        draft.blocking_reasons = blockers
        draft.status = str(
            verdict.get("status")
            or ("execute_ready" if verdict.get("ready") else "blocked")
        )
        if bool(verdict.get("compile_ready")):
            draft.compiled_dag_payload = draft.compiled_dag_payload or self._compiler.compile(
                draft
            )
        else:
            draft.compiled_dag_payload = None
        self._db.add(draft)
        self._db.commit()
        self._db.refresh(draft)
        return draft

    def refresh_readiness(self, draft_id: int) -> DataMakepoolFlowDraft | None:
        """重新执行 gate，并根据结果更新主表状态。"""

        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None
        verdict = self._gate.evaluate(draft)
        return self.apply_readiness_verdict(draft_id, verdict=verdict.to_dict())

    def _attach_to_session(self, *, session_id: int, draft_id: int) -> None:
        self._db.query(DataMakepoolConversationSession).filter(
            DataMakepoolConversationSession.id == session_id
        ).update(
            {"active_flow_draft_id": draft_id},
            synchronize_session="fetch",
        )

    def _sync_child_rows(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        steps: list[dict[str, Any]],
        params: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
    ) -> None:
        draft.step_rows.clear()
        draft.param_rows.clear()
        draft.mapping_rows.clear()

        for raw in steps:
            draft.step_rows.append(
                DataMakepoolFlowDraftStep(
                    step_key=str(raw["step_key"]),
                    title=str(raw.get("title") or raw["step_key"]),
                    executor_type=str(raw.get("executor_type") or ""),
                    target_ref=self._normalize_text(raw.get("target_ref")),
                    description=self._normalize_text(raw.get("description")),
                    step_order=int(raw.get("step_order") or 1),
                    status=str(raw.get("status") or "drafting"),
                    dependencies=list(raw.get("dependencies") or []),
                    config_payload=dict(raw.get("config_payload") or {}),
                    output_contract=dict(raw.get("output_contract") or {}),
                    blocking_reason=self._normalize_text(raw.get("blocking_reason")),
                )
            )

        for raw in params:
            draft.param_rows.append(
                DataMakepoolFlowDraftParam(
                    param_key=str(raw["param_key"]),
                    label=self._normalize_text(raw.get("label")),
                    value_payload=raw.get("value_payload"),
                    source_type=str(raw.get("source_type") or "session_fact"),
                    required=1 if raw.get("required") else 0,
                    status=str(raw.get("status") or "pending"),
                    blocking_reason=self._normalize_text(raw.get("blocking_reason")),
                    source_ref=self._normalize_text(raw.get("source_ref")),
                    notes=self._normalize_text(raw.get("notes")),
                )
            )

        for raw in mappings:
            draft.mapping_rows.append(
                DataMakepoolFlowDraftMapping(
                    target_step_key=str(raw["target_step_key"]),
                    target_field=str(raw["target_field"]),
                    source_kind=str(raw.get("source_kind") or "draft_param"),
                    source_ref=self._normalize_text(raw.get("source_ref")),
                    source_path=self._normalize_text(raw.get("source_path")),
                    literal_value=raw.get("literal_value"),
                    required=1 if raw.get("required", True) else 0,
                    status=str(raw.get("status") or "pending"),
                    blocking_reason=self._normalize_text(raw.get("blocking_reason")),
                    notes=self._normalize_text(raw.get("notes")),
                )
            )

    def _build_param_rows(self, *, fact_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in (
            "target_system",
            "target_entity",
            "execution_method",
            "target_environment",
            "data_count",
            "field_constraints",
            "data_dependencies",
            "reuse_strategy",
            "selected_candidate_id",
            "selected_source_type",
        ):
            value = fact_snapshot.get(key)
            required = key in self.REQUIRED_PARAM_KEYS
            has_value = value not in (None, "", [], {})
            rows.append(
                {
                    "param_key": key,
                    "label": self.PARAM_LABELS.get(key, key),
                    "value_payload": {"value": value} if has_value else None,
                    "source_type": "session_fact",
                    "required": required,
                    "status": "ready" if has_value else ("blocked" if required else "pending"),
                    "blocking_reason": (
                        f"缺少 {self.PARAM_LABELS.get(key, key)}"
                        if required and not has_value
                        else None
                    ),
                }
            )
        return rows

    def _build_step_rows(
        self,
        *,
        fact_snapshot: dict[str, Any],
        source_candidate_type: str | None,
        source_candidate_id: str | None,
        draft_patch: dict[str, Any],
    ) -> list[dict[str, Any]]:
        patch_steps = draft_patch.get("steps")
        if isinstance(patch_steps, list) and patch_steps:
            normalized = [self._normalize_step_patch(item, index) for index, item in enumerate(patch_steps)]
            if normalized:
                return normalized

        execution_method = self._normalize_text(fact_snapshot.get("execution_method")) or "auto"
        target_entity = self._normalize_text(fact_snapshot.get("target_entity"))
        target_system = self._normalize_text(fact_snapshot.get("target_system"))
        title = self.EXECUTOR_LABELS.get(execution_method, "造数执行")

        if source_candidate_type == "sql_asset":
            return [
                {
                    "step_key": "reuse_sql_asset",
                    "title": "复用 SQL 资产",
                    "executor_type": "sql",
                    "target_ref": source_candidate_id,
                    "description": "基于已选 SQL 资产继续执行或 probe。",
                    "step_order": 1,
                    "status": "drafting",
                    "dependencies": [],
                    "config_payload": {"mode": "reuse"},
                    "output_contract": {},
                }
            ]
        if source_candidate_type == "http_asset":
            return [
                {
                    "step_key": "reuse_http_asset",
                    "title": "复用 HTTP 资产",
                    "executor_type": "http",
                    "target_ref": source_candidate_id,
                    "description": "基于已选 HTTP 资产继续执行或 probe。",
                    "step_order": 1,
                    "status": "drafting",
                    "dependencies": [],
                    "config_payload": {"mode": "reuse"},
                    "output_contract": {},
                }
            ]
        if source_candidate_type == "template":
            return [
                {
                    "step_key": "reuse_template",
                    "title": "复用模板骨架",
                    "executor_type": "template",
                    "target_ref": source_candidate_id,
                    "description": "基于已选模板继续规划或直跑。",
                    "step_order": 1,
                    "status": "drafting",
                    "dependencies": [],
                    "config_payload": {"mode": "reuse"},
                    "output_contract": {},
                }
            ]
        if source_candidate_type == "legacy_scenario":
            return [
                {
                    "step_key": "reuse_legacy_scenario",
                    "title": "复用存量场景",
                    "executor_type": "legacy_scenario",
                    "target_ref": source_candidate_id,
                    "description": "优先尝试复用已有造数场景。",
                    "step_order": 1,
                    "status": "drafting",
                    "dependencies": [],
                    "config_payload": {"mode": "reuse"},
                    "output_contract": {},
                }
            ]

        return [
            {
                "step_key": "generated_data_flow",
                "title": title,
                "executor_type": execution_method,
                "target_ref": target_entity or target_system,
                "description": "基于当前会话信息生成首版执行草稿。",
                "step_order": 1,
                "status": "drafting",
                "dependencies": [],
                "config_payload": {"mode": "generated"},
                "output_contract": {},
                "blocking_reason": None if (target_entity or target_system) else "缺少目标对象",
            }
        ]

    def _build_mapping_rows(
        self,
        *,
        steps: list[dict[str, Any]],
        params: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        status_by_param = {
            str(row["param_key"]): str(row.get("status") or "pending")
            for row in params
        }
        rows: list[dict[str, Any]] = []
        for step in steps:
            step_key = str(step["step_key"])
            for param_key in (
                "target_system",
                "target_entity",
                "target_environment",
                "execution_method",
                "data_count",
                "field_constraints",
                "data_dependencies",
            ):
                required = param_key in self.REQUIRED_PARAM_KEYS
                status = status_by_param.get(param_key, "pending")
                rows.append(
                    {
                        "target_step_key": step_key,
                        "target_field": param_key,
                        "source_kind": "draft_param",
                        "source_ref": param_key,
                        "required": required,
                        "status": "ready" if status == "ready" else ("blocked" if required else "pending"),
                        "blocking_reason": (
                            f"{step_key}.{param_key} 缺少可用来源"
                            if required and status != "ready"
                            else None
                        ),
                    }
                )
        return rows

    @staticmethod
    def _build_param_graph(*, mappings: list[dict[str, Any]]) -> dict[str, Any]:
        graph: dict[str, Any] = {}
        for mapping in mappings:
            if mapping.get("source_kind") != "draft_param" or not mapping.get("source_ref"):
                continue
            graph[str(mapping["target_field"])] = {
                "source_kind": "draft_param",
                "source_ref": mapping.get("source_ref"),
                "target_step_key": mapping.get("target_step_key"),
                "required": bool(mapping.get("required", True)),
                "status": mapping.get("status"),
            }
        return graph

    @staticmethod
    def _normalize_step_patch(raw: Any, index: int) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {
                "step_key": f"patched_step_{index + 1}",
                "title": f"patched_step_{index + 1}",
                "executor_type": "auto",
                "target_ref": None,
                "description": None,
                "step_order": index + 1,
                "status": "drafting",
                "dependencies": [],
                "config_payload": {},
                "output_contract": {},
            }
        step_key = str(raw.get("step_key") or raw.get("name") or f"patched_step_{index + 1}")
        return {
            "step_key": step_key,
            "title": str(raw.get("title") or raw.get("name") or step_key),
            "executor_type": str(raw.get("executor_type") or raw.get("type") or "auto"),
            "target_ref": raw.get("target_ref"),
            "description": raw.get("description"),
            "step_order": int(raw.get("step_order") or index + 1),
            "status": str(raw.get("status") or "drafting"),
            "dependencies": list(raw.get("dependencies") or []),
            "config_payload": dict(raw.get("config_payload") or raw.get("config") or {}),
            "output_contract": dict(raw.get("output_contract") or {}),
            "blocking_reason": raw.get("blocking_reason"),
        }

    @staticmethod
    def _normalize_text(value: Any) -> str | None:
        text = str(value).strip() if value not in (None, "", [], {}) else ""
        return text or None

    @staticmethod
    def _should_rotate_version(
        *,
        draft: DataMakepoolFlowDraft,
        source_candidate_type: str | None,
        source_candidate_id: str | None,
    ) -> bool:
        return (
            str(draft.source_candidate_type or "") != str(source_candidate_type or "")
            or str(draft.source_candidate_id or "") != str(source_candidate_id or "")
        )

    @staticmethod
    def _find_param_row(draft: DataMakepoolFlowDraft, param_key: str) -> DataMakepoolFlowDraftParam | None:
        for row in list(draft.param_rows or []):
            if str(row.param_key) == param_key:
                return row
        return None

    @staticmethod
    def _find_mapping_row(
        draft: DataMakepoolFlowDraft,
        *,
        target_step_key: str,
        target_field: str,
    ) -> DataMakepoolFlowDraftMapping | None:
        for row in list(draft.mapping_rows or []):
            if str(row.target_step_key) == target_step_key and str(row.target_field) == target_field:
                return row
        return None

    @staticmethod
    def _find_step_row(draft: DataMakepoolFlowDraft, step_key: str) -> DataMakepoolFlowDraftStep | None:
        for row in list(draft.step_rows or []):
            if str(row.step_key) == step_key:
                return row
        return None

    def _apply_param_updates(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        updates: list[dict[str, Any]],
    ) -> None:
        for update in updates:
            param_key = self._normalize_text(update.get("param_key"))
            if not param_key:
                continue
            row = self._find_param_row(draft, param_key)
            if row is None:
                continue
            if "value" in update:
                row.value_payload = {"value": update.get("value")}
            if "status" in update:
                row.status = str(update.get("status") or row.status)
            if "blocking_reason" in update:
                row.blocking_reason = self._normalize_text(update.get("blocking_reason"))
            if "source_ref" in update:
                row.source_ref = self._normalize_text(update.get("source_ref"))

    def _apply_mapping_updates(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        updates: list[dict[str, Any]],
    ) -> None:
        for update in updates:
            step_key = self._normalize_text(update.get("target_step_key"))
            target_field = self._normalize_text(update.get("target_field"))
            if not step_key or not target_field:
                continue
            row = self._find_mapping_row(draft, target_step_key=step_key, target_field=target_field)
            if row is None:
                continue
            if "status" in update:
                row.status = str(update.get("status") or row.status)
            if "blocking_reason" in update:
                row.blocking_reason = self._normalize_text(update.get("blocking_reason"))
            if "source_ref" in update:
                row.source_ref = self._normalize_text(update.get("source_ref"))
            if "source_kind" in update:
                row.source_kind = str(update.get("source_kind") or row.source_kind)

    def _apply_step_updates(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        updates: list[dict[str, Any]],
    ) -> None:
        for update in updates:
            step_key = self._normalize_text(update.get("step_key"))
            if not step_key:
                continue
            row = self._find_step_row(draft, step_key)
            if row is None:
                continue
            if "status" in update:
                row.status = str(update.get("status") or row.status)
            if "blocking_reason" in update:
                row.blocking_reason = self._normalize_text(update.get("blocking_reason"))
            if "target_ref" in update:
                row.target_ref = self._normalize_text(update.get("target_ref"))

    def _merge_existing_step_state(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        steps: list[dict[str, Any]],
    ) -> None:
        existing = {
            str(row.step_key): row
            for row in list(draft.step_rows or [])
        }
        for step in steps:
            current = existing.get(str(step["step_key"]))
            if current is None:
                continue
            step["status"] = str(current.status or step.get("status") or "drafting")
            if current.blocking_reason:
                step["blocking_reason"] = current.blocking_reason
            if current.target_ref and not step.get("target_ref"):
                step["target_ref"] = current.target_ref

    def _merge_existing_param_state(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        params: list[dict[str, Any]],
    ) -> None:
        existing = {
            str(row.param_key): row
            for row in list(draft.param_rows or [])
        }
        for param in params:
            current = existing.get(str(param["param_key"]))
            if current is None:
                continue
            if current.value_payload and not param.get("value_payload"):
                param["value_payload"] = current.value_payload
            if current.status and current.status != "pending":
                param["status"] = str(current.status)
            if current.blocking_reason and not param.get("blocking_reason"):
                param["blocking_reason"] = current.blocking_reason
            if current.source_ref and not param.get("source_ref"):
                param["source_ref"] = current.source_ref

    def _merge_existing_mapping_state(
        self,
        *,
        draft: DataMakepoolFlowDraft,
        mappings: list[dict[str, Any]],
    ) -> None:
        existing = {
            (str(row.target_step_key), str(row.target_field)): row
            for row in list(draft.mapping_rows or [])
        }
        for mapping in mappings:
            key = (str(mapping["target_step_key"]), str(mapping["target_field"]))
            current = existing.get(key)
            if current is None:
                continue
            if current.status and current.status != "pending":
                mapping["status"] = str(current.status)
            if current.blocking_reason and not mapping.get("blocking_reason"):
                mapping["blocking_reason"] = current.blocking_reason
            if current.source_ref and not mapping.get("source_ref"):
                mapping["source_ref"] = current.source_ref
