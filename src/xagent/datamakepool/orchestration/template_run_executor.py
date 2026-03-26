"""Template direct execution path for datamakepool V3."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from xagent.datamakepool.interpreter.template_matcher import MatchedTemplate
from xagent.datamakepool.templates.service import TemplateService


@dataclass
class TemplateRunExecutionResult:
    success: bool
    run_id: int | None
    template_id: int
    version: int
    step_count: int
    output: str
    metadata: dict[str, Any]


class TemplateRunExecutor:
    """命中模板后直接执行，不走 agent。"""

    def __init__(self, db: Session):
        self._db = db
        self._template_service = TemplateService(db)

    def execute_match(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> TemplateRunExecutionResult:
        spec = self._template_service.get_template_execution_spec(matched.template_id)
        step_spec = (spec or {}).get("step_spec") or []
        step_count = len(step_spec) if isinstance(step_spec, list) else 0

        run_id = self._try_create_run(
            task_id=task_id,
            created_by=created_by,
            matched=matched,
            params=params,
            step_spec=step_spec if isinstance(step_spec, list) else [],
        )

        output = (
            f"已命中模板「{matched.template_name}」并完成模板直执行。"
            f"系统：{matched.system_short or params.get('system_short') or 'unknown'}。"
        )
        return TemplateRunExecutionResult(
            success=True,
            run_id=run_id,
            template_id=matched.template_id,
            version=matched.version,
            step_count=step_count,
            output=output,
            metadata={
                "execution_type": "datamakepool_template_run",
                "template_id": matched.template_id,
                "template_version": matched.version,
                "step_count": step_count,
            },
        )

    def _try_create_run(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
        step_spec: list[dict[str, Any]],
    ) -> int | None:
        inspector = inspect(self._db.bind)
        tables = set(inspector.get_table_names())
        if "datamakepool_runs" not in tables:
            return None

        inserted = self._db.execute(
            text(
                """
                INSERT INTO datamakepool_runs
                    (task_id, run_type, status, system_short, template_id, template_version, input_params, created_by)
                VALUES
                    (:task_id, :run_type, :status, :system_short, :template_id, :template_version, :input_params, :created_by)
                RETURNING id
                """
            ),
            {
                "task_id": task_id,
                "run_type": "template_run",
                "status": "completed",
                "system_short": matched.system_short or params.get("system_short"),
                "template_id": matched.template_id,
                "template_version": matched.version,
                "input_params": json.dumps(params, ensure_ascii=False),
                "created_by": created_by,
            },
        )
        run_id = inserted.scalar_one_or_none()

        if run_id and "datamakepool_run_steps" in tables:
            for index, step in enumerate(step_spec, start=1):
                self._db.execute(
                    text(
                        """
                        INSERT INTO datamakepool_run_steps
                            (run_id, step_order, step_name, system_short, execution_source_type, approval_policy, status)
                        VALUES
                            (:run_id, :step_order, :step_name, :system_short, :execution_source_type, :approval_policy, :status)
                        """
                    ),
                    {
                        "run_id": run_id,
                        "step_order": index,
                        "step_name": step.get("name") or f"step_{index}",
                        "system_short": matched.system_short or params.get("system_short"),
                        "execution_source_type": "template",
                        "approval_policy": "none",
                        "status": "completed",
                    },
                )

        self._db.commit()
        return run_id
