"""
`Template Draft Service`（模板草稿服务）模块。

这个服务负责承接 compile 产物，把它沉淀成“待审批、待编辑、待发布”的模板草稿工件。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from ..contracts.template_pipeline import (
    CompiledDagContract,
    TemplateDraftDigest,
)
from ..ledger.sql_models import DataMakeTemplateDraft
from ..ledger.sql_models import DataMakeTemplateVersion
from .models import FlowDraftAggregate


class TemplateDraftService:
    """
    `TemplateDraftService`（模板草稿服务）。

    设计边界：
    - 只维护模板草稿工件
    - 草稿状态只表达工件生命周期，不自动驱动发布或执行
    - 所有发布动作仍必须由主脑显式给出 `publish_template_version`
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory

    async def create_or_update_from_compiled_dag(
        self,
        *,
        task_id: str,
        aggregate: FlowDraftAggregate,
        compiled: CompiledDagContract,
    ) -> TemplateDraftDigest:
        """
        根据 compiled DAG 创建或刷新模板草稿。

        当前策略是：
        - 若最新草稿仍未发布，允许原地刷新，保持“当前工作草稿”稳定。
        - 若最新草稿已经被发布版本引用，则必须新建一条草稿，保护历史版本来源。
        - 审批/发布动作仍在后续显式链路里处理。
        """

        with self._new_session() as session:
            row = session.execute(
                select(DataMakeTemplateDraft)
                .where(DataMakeTemplateDraft.task_id == task_id)
                .order_by(desc(DataMakeTemplateDraft.id))
                .limit(1)
            ).scalar_one_or_none()

            if row is None or self._should_create_new_row(session=session, row=row):
                row = DataMakeTemplateDraft(task_id=task_id)
                session.add(row)

            row.status = "compiled" if not compiled.unresolved_mappings else "draft"
            row.flow_draft_version = aggregate.version
            row.compiled_dag_version = compiled.version
            row.draft_json = aggregate.model_dump(mode="json")
            row.compiled_dag_json = compiled.model_dump(mode="json")
            row.summary = compiled.goal_summary

            session.commit()
            session.refresh(row)

            return self._to_digest(row)

    def _should_create_new_row(
        self,
        *,
        session: Session,
        row: DataMakeTemplateDraft,
    ) -> bool:
        """
        判断当前 compile 是否必须新建模板草稿。

        关键约束：
        - 已被 `TemplateVersion` 引用的草稿是历史来源事实，后续 recompile 不能覆盖它。
        - 即使状态字段未来被人工改错，只要版本事实引用存在，也必须视为已发布来源。
        """

        if getattr(row, "id", None) is None:
            return False
        if row.status == "published":
            return True

        published_ref = session.execute(
            select(DataMakeTemplateVersion.id)
            .where(DataMakeTemplateVersion.template_draft_id == row.id)
            .limit(1)
        ).scalar_one_or_none()
        return published_ref is not None

    async def load_latest_digest(self, task_id: str) -> TemplateDraftDigest | None:
        """
        读取任务最新模板草稿摘要。
        """

        with self._new_session() as session:
            row = session.execute(
                select(DataMakeTemplateDraft)
                .where(DataMakeTemplateDraft.task_id == task_id)
                .order_by(desc(DataMakeTemplateDraft.id))
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._to_digest(row)

    def _to_digest(self, row: DataMakeTemplateDraft) -> TemplateDraftDigest:
        compiled_payload = row.compiled_dag_json if isinstance(row.compiled_dag_json, dict) else {}
        steps = compiled_payload.get("steps")
        unresolved = compiled_payload.get("unresolved_mappings")
        return TemplateDraftDigest(
            template_draft_id=row.id,
            task_id=row.task_id,
            status=row.status,
            flow_draft_version=row.flow_draft_version,
            compiled_dag_version=row.compiled_dag_version,
            goal_summary=row.summary or "",
            step_count=len(steps) if isinstance(steps, list) else 0,
            unresolved_mapping_count=len(unresolved) if isinstance(unresolved, list) else 0,
        )

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("TemplateDraftService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
