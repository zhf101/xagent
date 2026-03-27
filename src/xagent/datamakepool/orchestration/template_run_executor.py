"""模板直执行器。

当 planner 判断为 `template_direct` 时，这个执行器负责：
- 读取模板当前版本的执行规格
- 尽量写入 Run / RunStep 账本
- 返回一份对聊天层友好的执行结果摘要

当前版本重点是把“模板直跑这条路径”先跑通并留痕，
并没有真正逐步调用 HTTP / SQL / Dubbo 资产。
"""

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
    """模板直执行的返回结果。"""

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
        """执行一次模板命中结果。

        状态影响：
        - 尝试写入 `datamakepool_runs`
        - 如果存在步骤快照，再补写 `datamakepool_run_steps`
        - 成功后返回结构化结果，但当前不在这里拼装真实业务产物
        """

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
        """尽力写入 Run 与 RunStep 账本。

        关键约束：
        - 如果表还没建好，直接返回 `None`，不阻塞主流程
        - 这是“留痕优先”的 best-effort 行为，不把账本写入失败放大成执行失败
        """

        inspector = inspect(self._db.get_bind())
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

        # RunStep 目前只同步模板步骤骨架，状态统一记为 completed，
        # 表示“模板直执行路径已按版本定义完成登记”。
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
        if run_id:
            self._increment_used_count(matched.template_id)
        return run_id

    def _increment_used_count(self, template_id: int) -> None:
        """异步更新模板命中计数，失败时静默跳过。"""
        try:
            inspector = inspect(self._db.get_bind())
            if "template_stats" not in inspector.get_table_names():
                return
            self._db.execute(
                text(
                    """
                    INSERT INTO template_stats (template_id, views, likes, used_count)
                    VALUES (:tid, 0, 0, 1)
                    ON CONFLICT (template_id)
                    DO UPDATE SET used_count = template_stats.used_count + 1
                    """
                ),
                {"tid": template_id},
            )
            self._db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "模板 %s used_count 更新失败", template_id, exc_info=True
            )
