"""
`Compiled DAG Service`（编译后的 DAG 服务）模块。

这个服务负责把结构化 `FlowDraftAggregate` 冻结成 `CompiledDagContract`，
并把编译结果回写到 FlowDraft 宿主，供后续审批、模板草稿、运行时统一消费。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy.orm import Session, sessionmaker

from ..contracts.template_pipeline import CompiledDagContract, CompiledDagStep
from ..ledger.sql_models import DataMakeFlowDraft
from .flow_draft_projection_service import FlowDraftProjectionService
from .models import FlowDraftAggregate


class CompiledDagService:
    """
    `CompiledDagService`（编译后的 DAG 服务）。

    设计边界：
    - 输入只能是结构化 `FlowDraftAggregate`
    - compile 只产出可执行契约和 unresolved 信息，不替主脑决定下一步
    - 编译结果可持久化，但持久化的目的只是沉淀证据，不是触发自动执行
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory
        self.projection_service = FlowDraftProjectionService()

    async def compile(self, aggregate: FlowDraftAggregate) -> CompiledDagContract:
        """
        将结构化草稿编译成 `CompiledDagContract`，并回写到 FlowDraft 宿主。

        这里坚持两个约束：
        1. 只读取结构化草稿，不再回看自由文本
        2. 遇到 unresolved mapping 时显式暴露，而不是伪装成“编译已完全成功”
        """

        contract = CompiledDagContract(
            draft_id=f"draft_{aggregate.task_id}_v{aggregate.version}",
            version=aggregate.version,
            goal_summary=aggregate.goal_summary or "",
            steps=self._build_steps(aggregate),
            unresolved_mappings=self._build_unresolved_mappings(aggregate),
            metadata={
                "task_id": aggregate.task_id,
                "system_short": aggregate.system_short,
                "entity_name": aggregate.entity_name,
                "executor_kind": aggregate.executor_kind,
            },
        )

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, aggregate.task_id)
            if row is None:
                row = DataMakeFlowDraft(task_id=aggregate.task_id)
                session.add(row)

            aggregate_payload = aggregate.model_dump(mode="json")
            aggregate_payload["compiled_dag"] = contract.model_dump(mode="json")
            row.draft_json = self.projection_service.to_state(aggregate).model_dump(mode="json")
            row.structured_draft_json = aggregate_payload
            row.compiled_dag_json = contract.model_dump(mode="json")
            row.version = aggregate.version
            row.summary = aggregate.goal_summary
            session.commit()

        return contract

    async def load_digest(self, task_id: str) -> dict[str, Any] | None:
        """
        读取任务最近一次 compiled DAG 的轻量摘要。

        这个摘要只服务于 Agent / API 展示，避免上游在单轮上下文中搬运整份 DAG。
        """

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, task_id)
            if row is None or not isinstance(row.compiled_dag_json, dict):
                return None
            return self.build_digest_from_payload(row.compiled_dag_json)

    async def load_contract(self, task_id: str) -> CompiledDagContract | None:
        """
        读取任务最近一次 compiled DAG 完整契约。
        """

        with self._new_session() as session:
            row = session.get(DataMakeFlowDraft, task_id)
            if row is None or not isinstance(row.compiled_dag_json, dict):
                return None
            return CompiledDagContract.model_validate(row.compiled_dag_json)

    def build_digest(self, contract: CompiledDagContract) -> dict[str, Any]:
        """
        从编译契约构建轻量摘要。
        """

        return self.build_digest_from_payload(contract.model_dump(mode="json"))

    def build_digest_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        从持久化 payload 构建 compiled DAG 摘要。
        """

        steps = payload.get("steps")
        unresolved = payload.get("unresolved_mappings")
        return {
            "draft_id": payload.get("draft_id"),
            "version": payload.get("version"),
            "goal_summary": payload.get("goal_summary"),
            "step_count": len(steps) if isinstance(steps, list) else 0,
            "unresolved_mapping_count": len(unresolved) if isinstance(unresolved, list) else 0,
        }

    def _build_steps(self, aggregate: FlowDraftAggregate) -> list[CompiledDagStep]:
        steps: list[CompiledDagStep] = []
        for raw_step in aggregate.steps:
            if not isinstance(raw_step, dict):
                continue

            step_key = str(raw_step.get("step_key") or f"step_{len(steps) + 1}")
            step_kind = str(
                raw_step.get("kind")
                or raw_step.get("executor_type")
                or aggregate.executor_kind
                or "http"
            )
            dependencies = raw_step.get("dependencies")
            steps.append(
                CompiledDagStep(
                    step_key=step_key,
                    name=str(raw_step.get("name") or step_key),
                    kind=step_kind,  # type: ignore[arg-type]
                    dependencies=[
                        str(item) for item in dependencies if str(item).strip()
                    ]
                    if isinstance(dependencies, list)
                    else [],
                    input_snapshot=self._build_step_input_snapshot(
                        aggregate=aggregate,
                        raw_step=raw_step,
                    ),
                    config=self._build_step_config(
                        aggregate=aggregate,
                        raw_step=raw_step,
                    ),
                    approval_policy=str(raw_step.get("approval_policy") or "none"),
                )
            )
        return steps

    def _build_step_input_snapshot(
        self,
        *,
        aggregate: FlowDraftAggregate,
        raw_step: dict[str, Any],
    ) -> dict[str, Any]:
        ready_params = dict(aggregate.ready_params)
        explicit_snapshot = raw_step.get("input_snapshot")
        if isinstance(explicit_snapshot, dict):
            ready_params.update(explicit_snapshot)
        return ready_params

    def _build_step_config(
        self,
        *,
        aggregate: FlowDraftAggregate,
        raw_step: dict[str, Any],
    ) -> dict[str, Any]:
        """
        生成步骤配置快照。

        这里必须保留原始 step 的执行绑定信息，例如：
        - `resource_key / operation_key / tool_name`
        - `template_version_id / template_snapshot`
        - 未来可能出现的 `mcp_server / mcp_tool`

        之前若只保留 target_system/target_entity，会导致 compile 后真正执行所需的绑定信息丢失，
        进而让“草稿能 compile，但无法回放执行”。
        """

        config = dict(raw_step.get("config", {})) if isinstance(raw_step.get("config"), dict) else {}

        for key in (
            "resource_key",
            "operation_key",
            "tool_name",
            "template_version_id",
            "template_snapshot",
            "legacy_template_version_id",
            "legacy_template_snapshot",
            "scenario_key",
            "scenario_name",
            "mcp_server",
            "mcp_tool",
        ):
            if key in raw_step and raw_step.get(key) is not None and key not in config:
                config[key] = raw_step.get(key)

        config.setdefault("target_system", raw_step.get("target_system") or aggregate.system_short)
        config.setdefault("target_entity", raw_step.get("target_entity") or aggregate.entity_name)
        config.setdefault("executor_type", raw_step.get("executor_type") or aggregate.executor_kind)
        return config

    def _build_unresolved_mappings(
        self,
        aggregate: FlowDraftAggregate,
    ) -> list[dict[str, Any]]:
        unresolved: list[dict[str, Any]] = []
        for item in aggregate.mappings:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().lower()
            if status in {"ready", "resolved"}:
                continue
            unresolved.append(dict(item))
        return unresolved

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("CompiledDagService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
