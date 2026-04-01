"""
`Flow Draft Aggregate Service`（结构化流程草稿聚合服务）模块。

这个服务负责维护 FlowDraft 在服务层的结构化宿主形态，目标是让后续 compile
链路只读结构化事实，而不是回看自由文本或聊天历史。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy.orm import Session, sessionmaker

from ..ledger.sql_models import DataMakeFlowDraft
from .flow_draft_projection_service import FlowDraftProjectionService
from .models import FlowDraftAggregate, FlowDraftState


class FlowDraftAggregateService:
    """
    `FlowDraftAggregateService`（结构化流程草稿聚合服务）。

    主要职责：
    - 把当前轮结构化事实沉淀到 `FlowDraftAggregate`
    - 在保持最小侵入的前提下，兼容旧 `FlowDraftState` 的保存入口
    - 为后续 compile 服务提供稳定、可回放的结构化草稿输入
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory
        self.projection_service = FlowDraftProjectionService()

    async def load(self, task_id: str) -> FlowDraftAggregate | None:
        """
        读取任务当前的结构化草稿聚合根。

        优先读取 `structured_draft_json`；如果宿主还没升级过，则尝试从旧 `draft_json`
        推导一个最小可用聚合根，保证兼容已有任务。
        """

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, task_id)
            if row is None:
                return None

            structured_payload = row.structured_draft_json
            if isinstance(structured_payload, dict) and structured_payload:
                payload = dict(structured_payload)
                payload.setdefault("task_id", task_id)
                payload.setdefault("version", row.version)
                return FlowDraftAggregate.model_validate(payload)

            return self._build_aggregate_from_legacy_row(row=row)

    async def upsert_from_round_context(
        self,
        *,
        task_id: str,
        goal_summary: str,
        fact_snapshot: dict[str, Any],
        draft_patch: dict[str, Any] | None = None,
    ) -> FlowDraftAggregate:
        """
        用当前轮结构化事实更新草稿聚合根。

        这是给后续 ReAct 轮上下文/compile 链路用的主入口：
        - 输入必须是结构化 `fact_snapshot`
        - 输出是最新聚合根
        - 允许 `draft_patch` 做受控补丁，但不会让 patch 直接变成隐藏状态机
        """

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, task_id)
            aggregate = (
                self._build_aggregate_from_row(row=row)
                if row is not None
                else FlowDraftAggregate(task_id=task_id, version=1)
            )

            aggregate.goal_summary = goal_summary or aggregate.goal_summary
            aggregate.system_short = self._pick_text(
                fact_snapshot.get("target_system"),
                aggregate.system_short,
            )
            aggregate.entity_name = self._pick_text(
                fact_snapshot.get("target_entity"),
                aggregate.entity_name,
            )
            aggregate.executor_kind = self._pick_text(
                fact_snapshot.get("execution_method"),
                aggregate.executor_kind,
            )
            aggregate.steps = self._build_steps(goal_summary=goal_summary, fact_snapshot=fact_snapshot)
            aggregate.params = self._merge_params(
                existing=aggregate.params,
                fact_snapshot=fact_snapshot,
            )
            aggregate.mappings = self._merge_mappings(
                existing=aggregate.mappings,
                fact_snapshot=fact_snapshot,
            )
            aggregate.open_questions = self._build_open_questions(
                goal_summary=goal_summary,
                fact_snapshot=fact_snapshot,
                params=aggregate.params,
            )
            if isinstance(fact_snapshot.get("latest_risk"), str):
                aggregate.latest_risk = str(fact_snapshot["latest_risk"])
            if isinstance(fact_snapshot.get("last_execution_facts"), dict):
                aggregate.last_execution_facts = dict(fact_snapshot["last_execution_facts"])

            if draft_patch:
                aggregate = self._apply_draft_patch(aggregate=aggregate, draft_patch=draft_patch)

            aggregate.version = (row.version + 1) if row is not None else 1
            self._persist_aggregate(session=session, aggregate=aggregate, existing_row=row)
            return aggregate

    async def upsert_from_state(
        self,
        *,
        draft_state: FlowDraftState,
    ) -> FlowDraftAggregate:
        """
        用 `FlowDraftState` 更新结构化聚合根。

        这条入口的职责不是继续维持 `FlowDraftState` 为主链，
        而是给现有主循环一个安全过渡点：
        - 上层若暂时还只提供工作记忆视图，
        - 这里负责把它吸收到结构化 aggregate 宿主中，
        - 再由 projection_service 回投给主脑消费。
        """

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, draft_state.task_id)
            existing_aggregate = (
                self._build_aggregate_from_row(row=row)
                if row is not None
                else None
            )
            aggregate = self.build_from_state(
                draft_state=draft_state,
                existing_aggregate=existing_aggregate,
            )
            # 与旧 save 语义保持一致：调用方显式提供 version 时不擅自再跳版本。
            self._persist_aggregate(session=session, aggregate=aggregate, existing_row=row)
            return aggregate

    def build_from_state(
        self,
        *,
        draft_state: FlowDraftState,
        existing_aggregate: FlowDraftAggregate | None = None,
    ) -> FlowDraftAggregate:
        """
        用旧 `FlowDraftState` 兼容构造结构化聚合根。

        这条路径只服务于当前主脑的兼容保存逻辑：
        - 不要求它把所有步骤信息补全
        - 重点是把 confirmed/open/risk/facts 稳定落进结构化宿主
        """

        aggregate = existing_aggregate.model_copy(deep=True) if existing_aggregate else FlowDraftAggregate(
            task_id=draft_state.task_id,
            version=draft_state.version,
        )
        aggregate.goal_summary = draft_state.goal_summary
        aggregate.open_questions = list(draft_state.open_questions)
        aggregate.latest_risk = draft_state.latest_risk
        aggregate.last_execution_facts = dict(draft_state.last_execution_facts)
        aggregate.version = draft_state.version

        # 兼容旧主脑只知道 confirmed_params 的现状，这里不擅自猜测步骤，
        # 只把确定参数收进结构化参数池。
        for key, value in draft_state.confirmed_params.items():
            aggregate.params[key] = {
                "value": value,
                "status": "ready",
                "source": "flow_draft_state",
            }

        return aggregate

    def _build_aggregate_from_row(self, *, row: DataMakeFlowDraft) -> FlowDraftAggregate:
        structured_payload = row.structured_draft_json
        if isinstance(structured_payload, dict) and structured_payload:
            payload = dict(structured_payload)
            payload.setdefault("task_id", row.task_id)
            payload.setdefault("version", row.version)
            return FlowDraftAggregate.model_validate(payload)
        return self._build_aggregate_from_legacy_row(row=row)

    def _build_aggregate_from_legacy_row(self, *, row: DataMakeFlowDraft) -> FlowDraftAggregate:
        raw_payload = row.draft_json if isinstance(row.draft_json, dict) else {}
        state_payload = dict(raw_payload)
        state_payload.setdefault("task_id", row.task_id)
        state_payload.setdefault("version", row.version)
        state = FlowDraftState.model_validate(state_payload)
        return self.build_from_state(draft_state=state)

    def _persist_aggregate(
        self,
        *,
        session: Session,
        aggregate: FlowDraftAggregate,
        existing_row: DataMakeFlowDraft | None,
    ) -> None:
        row = existing_row
        if row is None:
            row = DataMakeFlowDraft(task_id=aggregate.task_id)
            session.add(row)

        projection = self.projection_service.to_state(aggregate)
        row.draft_json = projection.model_dump(mode="json")
        row.structured_draft_json = aggregate.model_dump(mode="json")
        row.version = aggregate.version
        row.summary = aggregate.goal_summary
        row.compiled_dag_json = aggregate.compiled_dag
        session.commit()

    def _build_steps(
        self,
        *,
        goal_summary: str,
        fact_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        executor_type = self._pick_text(fact_snapshot.get("execution_method"), "unknown")
        target_entity = self._pick_text(fact_snapshot.get("target_entity"), "unknown_target")
        step_key = str(target_entity).strip().replace(" ", "_") or "step_1"
        return [
            {
                "step_key": step_key,
                "name": goal_summary or f"执行 {target_entity}",
                "executor_type": executor_type,
                "target_system": self._pick_text(fact_snapshot.get("target_system"), None),
                "target_entity": target_entity,
            }
        ]

    def _merge_params(
        self,
        *,
        existing: dict[str, dict[str, Any]],
        fact_snapshot: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        params = {key: dict(value) for key, value in existing.items()}
        for key in ("target_system", "target_entity", "execution_method", "target_environment", "data_count"):
            if key in fact_snapshot:
                params[key] = {
                    "value": fact_snapshot.get(key),
                    "status": "ready" if fact_snapshot.get(key) not in (None, "", []) else "missing",
                    "source": "fact_snapshot",
                }
            else:
                params.setdefault(
                    key,
                    {
                        "value": None,
                        "status": "missing",
                        "source": "fact_snapshot",
                    },
                )
        return params

    def _merge_mappings(
        self,
        *,
        existing: list[dict[str, Any]],
        fact_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        mappings = [dict(item) for item in existing]
        if "field_mappings" in fact_snapshot and isinstance(fact_snapshot["field_mappings"], list):
            return [dict(item) for item in fact_snapshot["field_mappings"] if isinstance(item, dict)]
        return mappings

    def _build_open_questions(
        self,
        *,
        goal_summary: str,
        fact_snapshot: dict[str, Any],
        params: dict[str, dict[str, Any]],
    ) -> list[str]:
        questions: list[str] = []
        required_labels = {
            "target_system": "需要确认目标业务系统",
            "target_entity": "需要确认目标接口或实体",
            "execution_method": "需要确认采用 SQL、HTTP 还是历史场景复用",
            "target_environment": "需要确认执行环境",
            "data_count": "需要确认造数数量",
        }
        for key, question in required_labels.items():
            param_state = params.get(key) or {}
            if param_state.get("status") != "ready":
                questions.append(question)
        if not questions and not goal_summary:
            questions.append("需要确认本次造数目标")
        return questions

    def _apply_draft_patch(
        self,
        *,
        aggregate: FlowDraftAggregate,
        draft_patch: dict[str, Any],
    ) -> FlowDraftAggregate:
        patched = aggregate.model_copy(deep=True)
        if "open_questions" in draft_patch and isinstance(draft_patch["open_questions"], list):
            patched.open_questions = [str(item) for item in draft_patch["open_questions"]]
        if "latest_risk" in draft_patch:
            patched.latest_risk = (
                None if draft_patch["latest_risk"] is None else str(draft_patch["latest_risk"])
            )
        if "last_execution_facts" in draft_patch and isinstance(
            draft_patch["last_execution_facts"], dict
        ):
            patched.last_execution_facts = dict(draft_patch["last_execution_facts"])
        return patched

    def _pick_text(self, value: Any, default: str | None) -> str | None:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("FlowDraftAggregateService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
