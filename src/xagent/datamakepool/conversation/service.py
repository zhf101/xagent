"""智能造数平台 Phase 1 会话决策服务。

当前实现目标：
1. 把 data_generation 的入口从“直接规划/执行”切换为“先产出会话决策”
2. 支持两类首轮响应：
   - 有候选：展示候选并等待用户确认
   - 无候选：要求用户补齐关键业务信息
3. 在用户回复后，把结构化字段写回会话事实快照，并决定：
   - 继续澄清
   - 或进入正式执行

注意：
- 这是设计文档 v4 的 Phase 1 落地，不试图在本文件里一次性实现完整终态
- Probe、完整 DecisionFrame、ExecutionRun 统一建模会在后续 phase 继续补齐
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_conversation import (
    DataMakepoolCandidateChoice,
    DataMakepoolConversationSession,
    DataMakepoolRecallSnapshot,
)
from xagent.web.models.task import Task
from .decision_engine import DataGenerationDecisionEngine
from .runtime_service import ConversationRuntimeService

DATA_GENERATION_REQUIRED_FIELDS = (
    "target_system",
    "target_entity",
    "execution_method",
    "target_environment",
)

_FIELD_LABEL_MAP = {
    "目标系统": "target_system",
    "目标表/接口": "target_entity",
    "目标表名或接口": "target_entity",
    "执行方式": "execution_method",
    "目标环境": "target_environment",
    "数据量": "data_count",
    "字段约束": "field_constraints",
    "字段约束 / 业务规则": "field_constraints",
    "数据依赖": "data_dependencies",
    "请选择操作方式": "reuse_strategy",
    "操作方式": "reuse_strategy",
}

_EXECUTION_METHOD_LABEL_TO_VALUE = {
    "SQL 直接写入": "sql",
    "HTTP 接口调用": "http",
    "Dubbo 服务调用": "dubbo",
    "自动选择（推荐）": "auto",
    "自动选择": "auto",
}


@dataclass
class DataGenerationConversationDecision:
    """会话决策结果。

    `chat_response` 不再表达“聊天模式”语义，而是当前阶段前端要展示的 UI 载荷。
    当前 Phase 1 仍通过它兼容现有前端渲染。
    """

    should_pause_for_user: bool
    state: str
    chat_response: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    execution_context: dict[str, Any] | None = None


class DataGenerationConversationService:
    """智能造数平台的 Phase 1 会话驱动服务。"""

    def __init__(self, db: Session):
        self._db = db
        self._runtime = ConversationRuntimeService(db)
        self._decision_engine = DataGenerationDecisionEngine()

    def get_or_create_session(
        self,
        *,
        task: Task,
        user_id: int,
        goal: str,
    ) -> DataMakepoolConversationSession:
        """获取或创建 task 对应的造数会话。"""

        session = (
            self._db.query(DataMakepoolConversationSession)
            .filter(DataMakepoolConversationSession.task_id == int(task.id))
            .first()
        )
        if session is not None:
            return session

        session = DataMakepoolConversationSession(
            task_id=int(task.id),
            user_id=int(user_id),
            state="created",
            goal=goal,
            latest_summary="会话已创建，等待入口召回与首轮确认",
            fact_snapshot={},
        )
        self._db.add(session)
        self._db.commit()
        self._db.refresh(session)
        return session

    def build_initial_decision(
        self,
        *,
        task: Task,
        user_id: int,
        goal: str,
        entry_recall: Any,
    ) -> DataGenerationConversationDecision:
        """基于入口统一召回结果生成首轮会话决策。"""

        session = self.get_or_create_session(task=task, user_id=user_id, goal=goal)
        snapshot = self._upsert_recall_snapshot(session, entry_recall)
        self._sync_candidate_choices(session, entry_recall)

        has_candidates = self._has_any_candidates(entry_recall)
        decision = self._decision_engine.decide_after_recall(
            has_candidates=has_candidates
        )
        state_before = str(session.state)
        if has_candidates:
            session.state = decision.next_state
            session.active_recall_snapshot_id = int(snapshot.id)
            session.latest_summary = "入口召回已命中候选，等待用户确认处理方式"
            self._db.add(session)
            self._db.commit()
            self._runtime.record_decision(
                session=session,
                state_before=state_before,
                input_event_type="RECALL_FINISHED",
                recommended_action=decision.recommended_action,
                state_after=session.state,
                allowed_actions=decision.allowed_actions,
                rationale=decision.rationale,
            )
            return DataGenerationConversationDecision(
                should_pause_for_user=True,
                state=session.state,
                chat_response=self._build_candidate_chat_response(entry_recall),
                ui=self._build_candidate_ui(entry_recall),
            )

        session.state = decision.next_state
        session.active_recall_snapshot_id = int(snapshot.id)
        session.latest_summary = "未命中可直接复用候选，等待用户补齐业务信息"
        self._db.add(session)
        self._db.commit()
        self._runtime.record_decision(
            session=session,
            state_before=state_before,
            input_event_type="RECALL_FINISHED",
            recommended_action=decision.recommended_action,
            state_after=session.state,
            allowed_actions=decision.allowed_actions,
            rationale=decision.rationale,
        )
        return DataGenerationConversationDecision(
            should_pause_for_user=True,
            state=session.state,
            chat_response=self._build_clarification_chat_response(
                entry_recall=entry_recall,
                fact_snapshot=session.fact_snapshot or {},
            ),
            ui=self._build_clarification_ui(
                fact_snapshot=session.fact_snapshot or {},
                missing_fields=list(DATA_GENERATION_REQUIRED_FIELDS)
                + ["field_constraints"],
            ),
        )

    def consume_user_message(
        self,
        *,
        task: Task,
        user_id: int,
        user_message: str,
    ) -> DataGenerationConversationDecision:
        """消费用户补充信息，并决定是否继续澄清或进入执行。"""

        session = self.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )
        state_before = str(session.state)
        fact_snapshot = dict(session.fact_snapshot or {})
        parsed = self._parse_user_message(user_message)
        fact_snapshot.update(parsed)
        return self._decide_with_updated_facts(
            session=session,
            state_before=state_before,
            fact_snapshot=fact_snapshot,
            input_event_type="USER_FREE_TEXT",
            user_message=user_message,
        )

    def apply_fact_updates(
        self,
        *,
        task: Task,
        user_id: int,
        updates: dict[str, Any],
    ) -> DataGenerationConversationDecision:
        """应用结构化事实更新，并重新做一轮会话决策。"""

        session = self.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or ""),
        )
        state_before = str(session.state)
        fact_snapshot = dict(session.fact_snapshot or {})
        for key, value in dict(updates or {}).items():
            if value in (None, ""):
                fact_snapshot.pop(str(key), None)
            else:
                fact_snapshot[str(key)] = value
        return self._decide_with_updated_facts(
            session=session,
            state_before=state_before,
            fact_snapshot=fact_snapshot,
            input_event_type="USER_SUBMIT_FIELDS",
            user_message=None,
        )

    def resolve_probe_request_from_message(
        self,
        *,
        task: Task,
        user_id: int,
        user_message: str,
    ) -> dict[str, Any] | None:
        """从自由文本中解析 probe 请求。

        当前策略偏保守：
        - 必须出现明显的试跑/探测意图词
        - 优先使用用户已选中的候选
        - 若未选中，则在当前 active recall snapshot 中尝试推断唯一或最显著候选
        """

        message = str(user_message or "").strip()
        if not message:
            return None
        if not any(keyword in message for keyword in ("试跑", "探测", "预览", "先跑一下")):
            return None

        session = self.get_or_create_session(
            task=task,
            user_id=user_id,
            goal=str(task.description or user_message),
        )
        fact_snapshot = dict(session.fact_snapshot or {})
        selected_candidate_id = str(fact_snapshot.get("selected_candidate_id") or "").strip()
        selected_source_type = str(fact_snapshot.get("selected_source_type") or "").strip()

        if selected_candidate_id and selected_source_type in {
            "sql_asset",
            "http_asset",
            "template",
        }:
            return {
                "probe_type": selected_source_type,
                "target_ref": selected_candidate_id,
                "payload": fact_snapshot,
                "mode": "preview",
            }

        latest_snapshot = self._get_active_recall_snapshot(session)
        if latest_snapshot is None:
            return None

        # 显式偏好：消息里提到 SQL / 接口 / 模板 时，按类型优先选择候选。
        if "sql" in message.lower() or "SQL" in message:
            candidate_id = self._pick_first_candidate_id(latest_snapshot.sql_asset_candidates)
            if candidate_id:
                return {
                    "probe_type": "sql_asset",
                    "target_ref": candidate_id,
                    "payload": fact_snapshot,
                    "mode": "preview",
                }
        if "接口" in message or "http" in message.lower():
            candidate_id = self._pick_first_candidate_id(latest_snapshot.http_asset_candidates)
            if candidate_id:
                return {
                    "probe_type": "http_asset",
                    "target_ref": candidate_id,
                    "payload": fact_snapshot,
                    "mode": "preview",
                }
        if "模板" in message:
            candidate_id = self._pick_first_candidate_id(latest_snapshot.template_candidates)
            if candidate_id:
                return {
                    "probe_type": "template",
                    "target_ref": candidate_id,
                    "payload": fact_snapshot,
                    "mode": "preview",
                }

        # 回退：若当前只存在单一候选类型，则默认试跑该类型的首个候选。
        typed_candidates = [
            ("template", latest_snapshot.template_candidates),
            ("sql_asset", latest_snapshot.sql_asset_candidates),
            ("http_asset", latest_snapshot.http_asset_candidates),
        ]
        non_empty = [(probe_type, candidates) for probe_type, candidates in typed_candidates if candidates]
        if len(non_empty) == 1:
            probe_type, candidates = non_empty[0]
            candidate_id = self._pick_first_candidate_id(candidates)
            if candidate_id:
                return {
                    "probe_type": probe_type,
                    "target_ref": candidate_id,
                    "payload": fact_snapshot,
                    "mode": "preview",
                }
        return None

    def _upsert_recall_snapshot(
        self,
        session: DataMakepoolConversationSession,
        entry_recall: Any,
    ) -> DataMakepoolRecallSnapshot:
        snapshot = (
            self._db.query(DataMakepoolRecallSnapshot)
            .filter(DataMakepoolRecallSnapshot.session_id == int(session.id))
            .order_by(DataMakepoolRecallSnapshot.id.desc())
            .first()
        )
        payload = {
            "selected_strategy": entry_recall.selected_strategy,
            "selected_candidate": self._serialize_candidate(
                entry_recall.selected_candidate
            ),
            "template_candidates": [
                self._serialize_candidate(item)
                for item in entry_recall.template_candidates
            ],
            "sql_asset_candidates": [
                self._serialize_candidate(item)
                for item in entry_recall.sql_asset_candidates
            ],
            "http_asset_candidates": [
                self._serialize_candidate(item)
                for item in entry_recall.http_asset_candidates
            ],
            "legacy_candidates": [
                self._serialize_candidate(item)
                for item in entry_recall.legacy_candidates
            ],
            "missing_params": list(entry_recall.missing_params or []),
            "debug_info": dict(entry_recall.debug or {}),
        }

        if snapshot is None:
            snapshot = DataMakepoolRecallSnapshot(
                session_id=int(session.id),
                turn_no=1,
                **payload,
            )
            self._db.add(snapshot)
        else:
            for key, value in payload.items():
                setattr(snapshot, key, value)

        self._db.commit()
        self._db.refresh(snapshot)
        return snapshot

    def _sync_candidate_choices(
        self,
        session: DataMakepoolConversationSession,
        entry_recall: Any,
    ) -> None:
        existing = {
            str(item.candidate_id): item
            for item in self._db.query(DataMakepoolCandidateChoice)
            .filter(DataMakepoolCandidateChoice.session_id == int(session.id))
            .all()
        }
        for source_type, candidates in (
            ("template", entry_recall.template_candidates),
            ("sql_asset", entry_recall.sql_asset_candidates),
            ("http_asset", entry_recall.http_asset_candidates),
            ("legacy_scenario", entry_recall.legacy_candidates),
        ):
            for candidate in candidates:
                candidate_id = str(candidate.candidate_id)
                row = existing.get(candidate_id)
                payload = self._serialize_candidate(candidate)
                if row is None:
                    row = DataMakepoolCandidateChoice(
                        session_id=int(session.id),
                        source_type=source_type,
                        candidate_id=candidate_id,
                        display_name=str(candidate.display_name),
                        score=float(candidate.score or 0.0),
                        matched_signals=list(candidate.matched_signals or []),
                        summary=str(candidate.summary or ""),
                        payload=payload,
                        status="pending",
                    )
                    self._db.add(row)
                else:
                    row.display_name = str(candidate.display_name)
                    row.score = float(candidate.score or 0.0)
                    row.matched_signals = list(candidate.matched_signals or [])
                    row.summary = str(candidate.summary or "")
                    row.payload = payload
        self._db.commit()

    def _build_candidate_chat_response(self, entry_recall: Any) -> dict[str, Any]:
        interactions: list[dict[str, Any]] = []
        options: list[dict[str, str]] = []

        selected_candidate = entry_recall.selected_candidate
        if selected_candidate is not None:
            if entry_recall.selected_strategy == "template_direct":
                options.append(
                    {
                        "value": (
                            "execute:template_direct:"
                            f"template:{selected_candidate.payload.get('template_id')}"
                        ),
                        "label": f"直接执行模板「{selected_candidate.display_name}」",
                    }
                )
                options.append(
                    {
                        "value": f"reuse:template:{selected_candidate.payload.get('template_id')}",
                        "label": f"基于模板「{selected_candidate.display_name}」继续规划",
                    }
                )
            elif entry_recall.selected_strategy == "legacy_direct":
                options.append(
                    {
                        "value": f"execute:legacy_direct:legacy:{selected_candidate.candidate_id}",
                        "label": f"直接执行存量场景「{selected_candidate.display_name}」",
                    }
                )
                options.append(
                    {
                        "value": f"reuse:legacy:{selected_candidate.candidate_id}",
                        "label": f"基于存量场景「{selected_candidate.display_name}」继续规划",
                    }
                )

        for candidate in entry_recall.sql_asset_candidates[:1]:
            options.append(
                {
                    "value": f"reuse:sql:{candidate.candidate_id}",
                    "label": f"基于 SQL 资产「{candidate.display_name}」继续规划",
                }
            )
        for candidate in entry_recall.http_asset_candidates[:1]:
            options.append(
                {
                    "value": f"reuse:http:{candidate.candidate_id}",
                    "label": f"基于 HTTP 资产「{candidate.display_name}」继续规划",
                }
            )
        options.append({"value": "scratch", "label": "不复用，从零规划"})

        interactions.append(
            {
                "type": "select_one",
                "field": "reuse_strategy",
                "label": "请选择操作方式",
                "options": options,
            }
        )
        interactions.append(
            {
                "type": "number_input",
                "field": "data_count",
                "label": "数据量",
                "placeholder": "如：100",
                "min": 1,
            }
        )
        interactions.append(
            {
                "type": "text_input",
                "field": "target_environment",
                "label": "目标环境",
                "placeholder": "如：dev / test / staging",
            }
        )
        for item in list(entry_recall.missing_params or [])[:4]:
            field_name = str(item.get("field") or "").strip()
            if not field_name:
                continue
            interactions.append(
                {
                    "type": "text_input",
                    "field": field_name,
                    "label": str(item.get("label") or field_name),
                    "placeholder": f"请提供 {item.get('label') or field_name}",
                }
            )

        summary_lines = [
            "收到你的造数需求。平台已检索到以下可复用资产，请先确认处理方式："
        ]
        if entry_recall.template_candidates:
            summary_lines.append(
                f"- 模板：{entry_recall.template_candidates[0].display_name}"
            )
        if entry_recall.sql_asset_candidates:
            summary_lines.append(
                f"- SQL 资产：{entry_recall.sql_asset_candidates[0].display_name}"
            )
        if entry_recall.http_asset_candidates:
            summary_lines.append(
                f"- HTTP 资产：{entry_recall.http_asset_candidates[0].display_name}"
            )
        if entry_recall.legacy_candidates:
            summary_lines.append(
                f"- 存量场景：{entry_recall.legacy_candidates[0].display_name}"
            )

        return {
            "message": "\n".join(summary_lines),
            "interactions": interactions,
        }

    def _build_candidate_ui(self, entry_recall: Any) -> dict[str, Any]:
        chat_response = self._build_candidate_chat_response(entry_recall)
        candidates: list[dict[str, Any]] = []
        for source_type, items in (
            ("template", entry_recall.template_candidates),
            ("sql_asset", entry_recall.sql_asset_candidates),
            ("http_asset", entry_recall.http_asset_candidates),
            ("legacy_scenario", entry_recall.legacy_candidates),
        ):
            for item in items[:3]:
                candidates.append(
                    {
                        "source_type": source_type,
                        "candidate_id": getattr(item, "candidate_id", None),
                        "display_name": getattr(item, "display_name", None),
                        "score": getattr(item, "score", None),
                        "matched_signals": list(
                            getattr(item, "matched_signals", []) or []
                        ),
                        "summary": getattr(item, "summary", None),
                    }
                )
        return {
            "type": "candidate_choice_card",
            "message": chat_response["message"],
            "interactions": chat_response["interactions"],
            "data": {
                "selected_strategy": getattr(entry_recall, "selected_strategy", None),
                "candidates": candidates,
            },
        }

    def _build_clarification_chat_response(
        self,
        *,
        entry_recall: Any,
        fact_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        del entry_recall
        return {
            "message": (
                "平台未找到可直接复用的历史模板或资产，需要从零规划造数链路。"
                "为了生成准确的测试数据，请先补充关键业务信息："
            ),
            "interactions": self._build_missing_field_interactions(
                fact_snapshot=fact_snapshot,
                missing_fields=list(DATA_GENERATION_REQUIRED_FIELDS)
                + ["field_constraints"],
            ),
        }

    def _build_followup_clarification_response(
        self,
        *,
        fact_snapshot: dict[str, Any],
        missing_fields: list[str],
    ) -> dict[str, Any]:
        return {
            "message": "我已经收到你的部分补充信息，但还缺以下关键项，补齐后才能进入正式执行：",
            "interactions": self._build_missing_field_interactions(
                fact_snapshot=fact_snapshot,
                missing_fields=missing_fields,
            ),
        }

    def _build_clarification_ui(
        self,
        *,
        fact_snapshot: dict[str, Any],
        missing_fields: list[str],
    ) -> dict[str, Any]:
        interactions = self._build_missing_field_interactions(
            fact_snapshot=fact_snapshot,
            missing_fields=missing_fields,
        )
        return {
            "type": "clarification_form",
            "message": "请继续补充关键信息",
            "interactions": interactions,
        }

    def _build_missing_field_interactions(
        self,
        *,
        fact_snapshot: dict[str, Any],
        missing_fields: list[str],
    ) -> list[dict[str, Any]]:
        interactions: list[dict[str, Any]] = []
        for field in missing_fields:
            if field == "execution_method":
                interactions.append(
                    {
                        "type": "select_one",
                        "field": field,
                        "label": "执行方式",
                        "options": [
                            {"value": "sql", "label": "SQL 直接写入"},
                            {"value": "http", "label": "HTTP 接口调用"},
                            {"value": "dubbo", "label": "Dubbo 服务调用"},
                            {"value": "auto", "label": "自动选择（推荐）"},
                        ],
                    }
                )
                continue
            if field == "data_count":
                interactions.append(
                    {
                        "type": "number_input",
                        "field": field,
                        "label": "数据量",
                        "placeholder": str(fact_snapshot.get(field) or "如：100"),
                        "min": 1,
                    }
                )
                continue
            if field == "field_constraints":
                interactions.append(
                    {
                        "type": "text_input",
                        "field": field,
                        "label": "字段约束 / 业务规则",
                        "placeholder": "如：状态枚举、金额规则、时间先后关系",
                        "multiline": True,
                    }
                )
                continue
            label = {
                "target_system": "目标系统",
                "target_entity": "目标表名或接口",
                "target_environment": "目标环境",
                "data_dependencies": "数据依赖",
            }.get(field, field)
            interactions.append(
                {
                    "type": "text_input",
                    "field": field,
                    "label": label,
                    "placeholder": str(fact_snapshot.get(field) or f"请提供 {label}"),
                }
            )
        return interactions

    def _build_execution_context(
        self,
        *,
        session: DataMakepoolConversationSession,
    ) -> dict[str, Any]:
        fact_snapshot = dict(session.fact_snapshot or {})
        selected_candidate_id = fact_snapshot.get("selected_candidate_id")
        selected_source_type = fact_snapshot.get("selected_source_type")
        reuse_strategy = fact_snapshot.get("reuse_strategy")

        lines = [
            "你正在处理一个已经完成首轮用户确认的智能造数会话。",
            "以下信息来自会话状态机，而不是临时 prompt 推断。",
        ]
        for field, label in (
            ("target_system", "目标系统"),
            ("target_entity", "目标实体"),
            ("execution_method", "执行方式"),
            ("target_environment", "目标环境"),
            ("data_count", "数据量"),
            ("field_constraints", "字段约束"),
            ("data_dependencies", "数据依赖"),
        ):
            value = fact_snapshot.get(field)
            if value not in (None, "", []):
                lines.append(f"- {label}: {value}")
        if reuse_strategy:
            lines.append(f"- 用户确认的处理方式: {reuse_strategy}")
        if selected_candidate_id:
            lines.append(f"- 用户当前关注的候选对象: {selected_candidate_id}")
        if selected_source_type:
            lines.append(f"- 候选来源类型: {selected_source_type}")

        execution_goal = (
            f"{session.goal}\n\n用户补充与确认信息：\n" + "\n".join(lines[2:])
            if len(lines) > 2
            else session.goal
        )

        return {
            "datamakepool_conversation_session_id": int(session.id),
            "datamakepool_conversation_ready": True,
            "datamakepool_execution_choice": reuse_strategy or "scratch",
            "datamakepool_selected_candidate_id": selected_candidate_id,
            "datamakepool_selected_source_type": selected_source_type,
            "datamakepool_conversation_facts": fact_snapshot,
            "datamakepool_execution_goal": execution_goal,
            "system_prompt": "\n".join(lines),
        }

    def _decide_with_updated_facts(
        self,
        *,
        session: DataMakepoolConversationSession,
        state_before: str,
        fact_snapshot: dict[str, Any],
        input_event_type: str,
        user_message: str | None,
    ) -> DataGenerationConversationDecision:
        session.fact_snapshot = fact_snapshot

        latest_snapshot = self._get_active_recall_snapshot(session)
        if user_message:
            selected_choice = self._resolve_choice_from_message(
                latest_snapshot=latest_snapshot,
                user_message=user_message,
            )
            if selected_choice is not None:
                fact_snapshot["reuse_strategy"] = selected_choice["strategy"]
                fact_snapshot["selected_candidate_id"] = selected_choice.get(
                    "candidate_id"
                )
                fact_snapshot["selected_source_type"] = selected_choice.get(
                    "source_type"
                )
                session.fact_snapshot = fact_snapshot
                self._mark_selected_choice(session, selected_choice)

        missing_fields = self._compute_missing_fields(
            has_candidates=latest_snapshot is not None
            and self._snapshot_has_candidates(latest_snapshot),
            fact_snapshot=fact_snapshot,
        )
        decision = self._decision_engine.decide_after_user_message(
            missing_fields=missing_fields
        )

        if missing_fields:
            session.state = decision.next_state
            session.latest_summary = "用户已补充部分信息，但仍存在关键缺口，继续澄清"
            self._db.add(session)
            self._db.commit()
            self._runtime.record_decision(
                session=session,
                state_before=state_before,
                input_event_type=input_event_type,
                recommended_action=decision.recommended_action,
                state_after=session.state,
                allowed_actions=decision.allowed_actions,
                rationale=decision.rationale,
            )
            return DataGenerationConversationDecision(
                should_pause_for_user=True,
                state=session.state,
                chat_response=self._build_followup_clarification_response(
                    fact_snapshot=fact_snapshot,
                    missing_fields=missing_fields,
                ),
                ui=self._build_clarification_ui(
                    fact_snapshot=fact_snapshot,
                    missing_fields=missing_fields,
                ),
            )

        session.state = decision.next_state
        session.latest_summary = "关键业务信息已满足 Phase 1 入口要求，准备进入正式执行"
        self._db.add(session)
        self._db.commit()
        self._runtime.record_decision(
            session=session,
            state_before=state_before,
            input_event_type=input_event_type,
            recommended_action=decision.recommended_action,
            state_after=session.state,
            allowed_actions=decision.allowed_actions,
            rationale=decision.rationale,
        )
        execution_context = self._build_execution_context(session=session)
        return DataGenerationConversationDecision(
            should_pause_for_user=False,
            state=session.state,
            execution_context=execution_context,
        )

    def _parse_user_message(self, message: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if not message:
            return result

        lines = [line.strip() for line in message.splitlines() if line.strip()]
        for line in lines:
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            field = _FIELD_LABEL_MAP.get(key.strip(), key.strip())
            normalized_value = value.strip()
            if not normalized_value:
                continue
            if field == "data_count":
                digits = re.sub(r"[^\d]", "", normalized_value)
                if digits:
                    result[field] = int(digits)
                continue
            if field == "execution_method":
                result[field] = _EXECUTION_METHOD_LABEL_TO_VALUE.get(
                    normalized_value, normalized_value.lower()
                )
                continue
            result[field] = normalized_value

        if not result and message.strip():
            # 自由文本场景先归档为字段约束补充说明，避免信息彻底丢失。
            result["field_constraints"] = message.strip()
        return result

    def _compute_missing_fields(
        self,
        *,
        has_candidates: bool,
        fact_snapshot: dict[str, Any],
    ) -> list[str]:
        if has_candidates:
            # 已有召回候选时，首轮最低要求是用户先明确处理方式；
            # 其余字段作为增强信息，在缺失情况下允许后续进入 orchestrator 再继续澄清。
            missing: list[str] = []
            if not fact_snapshot.get("reuse_strategy"):
                missing.append("reuse_strategy")
            return missing

        missing = [
            field
            for field in DATA_GENERATION_REQUIRED_FIELDS
            if not fact_snapshot.get(field)
        ]
        return missing

    def _resolve_choice_from_message(
        self,
        *,
        latest_snapshot: DataMakepoolRecallSnapshot | None,
        user_message: str,
    ) -> dict[str, Any] | None:
        message = user_message.strip()
        if not message:
            return None

        if "从零规划" in message:
            return {"strategy": "scratch", "candidate_id": None, "source_type": None}

        if latest_snapshot is None:
            return None

        for source_type, key in (
            ("template", "template_candidates"),
            ("sql_asset", "sql_asset_candidates"),
            ("http_asset", "http_asset_candidates"),
            ("legacy_scenario", "legacy_candidates"),
        ):
            for candidate in list(getattr(latest_snapshot, key) or []):
                display_name = str(candidate.get("display_name") or "")
                candidate_id = str(candidate.get("candidate_id") or "")
                if display_name and display_name in message:
                    return {
                        "strategy": f"reuse:{source_type}",
                        "candidate_id": candidate_id,
                        "source_type": source_type,
                    }
        return None

    def _mark_selected_choice(
        self,
        session: DataMakepoolConversationSession,
        selected_choice: dict[str, Any],
    ) -> None:
        candidate_id = selected_choice.get("candidate_id")
        if not candidate_id:
            return
        row = (
            self._db.query(DataMakepoolCandidateChoice)
            .filter(
                DataMakepoolCandidateChoice.session_id == int(session.id),
                DataMakepoolCandidateChoice.candidate_id == str(candidate_id),
            )
            .first()
        )
        if row is None:
            return
        row.status = "confirmed"
        row.user_params = dict(session.fact_snapshot or {})
        self._db.add(row)
        self._db.commit()

    def _has_any_candidates(self, entry_recall: Any) -> bool:
        return any(
            [
                bool(entry_recall.template_candidates),
                bool(entry_recall.sql_asset_candidates),
                bool(entry_recall.http_asset_candidates),
                bool(entry_recall.legacy_candidates),
                entry_recall.selected_candidate is not None,
            ]
        )

    def _snapshot_has_candidates(
        self, snapshot: DataMakepoolRecallSnapshot | None
    ) -> bool:
        if snapshot is None:
            return False
        return any(
            [
                bool(snapshot.template_candidates),
                bool(snapshot.sql_asset_candidates),
                bool(snapshot.http_asset_candidates),
                bool(snapshot.legacy_candidates),
                snapshot.selected_candidate is not None,
            ]
        )

    def _get_active_recall_snapshot(
        self, session: DataMakepoolConversationSession
    ) -> DataMakepoolRecallSnapshot | None:
        if session.active_recall_snapshot_id:
            return (
                self._db.query(DataMakepoolRecallSnapshot)
                .filter(
                    DataMakepoolRecallSnapshot.id
                    == int(session.active_recall_snapshot_id)
                )
                .first()
            )
        return (
            self._db.query(DataMakepoolRecallSnapshot)
            .filter(DataMakepoolRecallSnapshot.session_id == int(session.id))
            .order_by(DataMakepoolRecallSnapshot.id.desc())
            .first()
        )

    @staticmethod
    def _pick_first_candidate_id(candidates: Any) -> str | None:
        for item in list(candidates or []):
            candidate_id = str(item.get("candidate_id") or "").strip()
            if candidate_id:
                return candidate_id
        return None

    def _serialize_candidate(self, candidate: Any) -> dict[str, Any] | None:
        if candidate is None:
            return None
        return {
            "source_type": getattr(candidate, "source_type", None),
            "candidate_id": getattr(candidate, "candidate_id", None),
            "display_name": getattr(candidate, "display_name", None),
            "system_short": getattr(candidate, "system_short", None),
            "score": getattr(candidate, "score", None),
            "matched_signals": list(getattr(candidate, "matched_signals", []) or []),
            "summary": getattr(candidate, "summary", None),
            "payload": getattr(candidate, "payload", None),
        }
