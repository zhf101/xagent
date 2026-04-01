"""
`Template Version Executor`（模板版本执行器）模块。

这个执行器负责把已发布模板版本快照重新送入 compiled DAG 执行链路，实现模板复跑。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from sqlalchemy.orm import Session, sessionmaker

from ..contracts.constants import RUNTIME_STATUS_FAILED
from ..contracts.runtime import RuntimeResult
from ..contracts.template_pipeline import CompiledDagStep, TemplateVersionSnapshot
from ..ledger.sql_models import DataMakeTemplateRun, DataMakeTemplateVersion


class TemplateVersionExecutor:
    """
    `TemplateVersionExecutor`（模板版本执行器）。

    设计边界：
    - 只消费已经发布的版本快照
    - 不回看 FlowDraft，不推导新模板
    - 复跑仍然走 compiled DAG 执行链路，而不是自己造一套执行语义
    """

    def __init__(
        self,
        *,
        compiled_dag_executor: Any,
        session_factory: sessionmaker[Session] | Any | None = None,
    ) -> None:
        self.compiled_dag_executor = compiled_dag_executor
        self.session_factory = session_factory

    async def execute(
        self,
        snapshot: TemplateVersionSnapshot,
        params: dict[str, Any],
    ) -> RuntimeResult:
        """
        执行一个模板版本快照。
        """

        result = await self.compiled_dag_executor.execute(
            snapshot.compiled_dag,
            runtime_inputs=params,
        )
        final_result = result.model_copy(
            update={
                "artifact_type": "template_version",
                "artifact_ref": {
                    "template_id": snapshot.template_id,
                    "version": snapshot.version,
                    "template_version_id": snapshot.template_version_id,
                },
                "summary": (
                    "模板版本执行完成"
                    if result.status != RUNTIME_STATUS_FAILED
                    else "模板版本执行失败"
                ),
            }
        )
        await self._record_run(snapshot=snapshot, params=params, result=final_result)
        return final_result

    async def execute_from_step(
        self,
        *,
        step: CompiledDagStep,
        params: Any,
    ) -> RuntimeResult:
        """
        执行嵌套在 compiled DAG 中的模板版本步骤。
        """

        snapshot_payload = step.config.get("template_snapshot")
        if isinstance(snapshot_payload, dict):
            snapshot = TemplateVersionSnapshot.model_validate(snapshot_payload)
            return await self.execute(snapshot, params if isinstance(params, dict) else {})

        template_version_id = step.config.get("template_version_id")
        if template_version_id is None:
            return RuntimeResult(
                run_id=f"template_version_step_{step.step_key}",
                status=RUNTIME_STATUS_FAILED,
                summary="模板版本步骤缺少 template_snapshot 或 template_version_id",
                facts={"step_key": step.step_key},
                error="template_version_binding_missing",
            )

        snapshot = await self.load_snapshot(int(template_version_id))
        if snapshot is None:
            return RuntimeResult(
                run_id=f"template_version_step_{step.step_key}",
                status=RUNTIME_STATUS_FAILED,
                summary="未找到要执行的模板版本快照",
                facts={"step_key": step.step_key, "template_version_id": template_version_id},
                error="template_version_not_found",
            )
        return await self.execute(snapshot, params if isinstance(params, dict) else {})

    async def load_snapshot(self, template_version_id: int) -> TemplateVersionSnapshot | None:
        """
        按模板版本 ID 读取冻结快照。
        """

        if self.session_factory is None:
            return None

        with self._new_session() as session:
            row = session.get(DataMakeTemplateVersion, template_version_id)
            if row is None or not isinstance(row.snapshot_json, dict):
                return None
            return TemplateVersionSnapshot.model_validate(row.snapshot_json)

    async def _record_run(
        self,
        *,
        snapshot: TemplateVersionSnapshot,
        params: dict[str, Any],
        result: RuntimeResult,
    ) -> None:
        """
        把模板版本执行结果写入 `DataMakeTemplateRun`。

        这层账本的职责不是驱动流程，而是给：
        - 检索排序
        - 成功率统计
        - 运行审计
        提供稳定事实来源。
        """

        if self.session_factory is None or snapshot.template_version_id is None:
            return

        with self._new_session() as session:
            row = DataMakeTemplateRun(
                task_id=snapshot.task_id or "",
                template_id=snapshot.template_id,
                template_version_id=int(snapshot.template_version_id),
                run_key=result.run_id,
                status=result.status,
                runtime_context_json={
                    "template_params": dict(params),
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                },
                result_json=result.model_dump(mode="json"),
            )
            session.add(row)
            session.commit()

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("TemplateVersionExecutor 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
