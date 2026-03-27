"""模板草稿提取器。

当前版本实现的是 v3 所需的最小闭环：
1. 从执行前的 execution_plan 骨架中提取步骤
2. 从参数快照中提取最小 parameter schema
3. 在执行成功后写入 datamakepool_template_drafts

注意：
- 当前不做完整 trace 级资产回放解析
- 当前不依赖不存在的 TemplateDraft ORM，直接走 SQLAlchemy text 落库
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


class TemplateDraftExtractor:
    def __init__(self, db: Session):
        self._db = db

    def extract_and_save(
        self,
        *,
        task_description: str,
        result: dict[str, Any],
        task_id: int,
        system_short: str | None,
        created_by: int,
        execution_plan: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        match_type: str | None = None,
    ) -> int | None:
        inspector = inspect(self._db.get_bind())
        if "datamakepool_template_drafts" not in inspector.get_table_names():
            return None

        if not result.get("success", False):
            return None

        step_spec = self._build_step_spec(execution_plan)
        step_spec = self._augment_step_spec_with_execution_result(step_spec, result)
        param_schema = self._build_param_schema(params or {})
        name = self._build_draft_name(task_description, task_id)
        tags = ["auto_extracted", "orchestrator_success"]
        if match_type:
            tags.append(match_type)

        row = self._db.execute(
            text(
                """
                INSERT INTO datamakepool_template_drafts
                    (template_id, name, system_short, status, description,
                     tags, applicable_systems, step_spec, param_schema, created_by)
                VALUES
                    (:template_id, :name, :system_short, :status, :description,
                     :tags, :applicable_systems, :step_spec, :param_schema, :created_by)
                """
            ),
            {
                "template_id": None,
                "name": name,
                "system_short": system_short or "unknown",
                "status": "draft",
                "description": task_description.strip(),
                "tags": json.dumps(tags, ensure_ascii=False),
                "applicable_systems": json.dumps(
                    [system_short] if system_short else [],
                    ensure_ascii=False,
                ),
                "step_spec": json.dumps(step_spec, ensure_ascii=False),
                "param_schema": json.dumps(param_schema, ensure_ascii=False),
                "created_by": created_by,
            },
        )
        self._db.commit()
        inserted_id = row.lastrowid if hasattr(row, "lastrowid") else None
        return int(inserted_id) if inserted_id is not None else None

    def _build_draft_name(self, task_description: str, task_id: int) -> str:
        summary = " ".join(task_description.strip().split())
        if len(summary) > 80:
            summary = f"{summary[:77]}..."
        return f"AutoDraft Task {task_id}: {summary}"

    def _build_step_spec(self, execution_plan: dict[str, Any] | None) -> dict[str, Any]:
        if not execution_plan:
            return {"steps": []}

        steps: list[dict[str, Any]] = []
        reusable_steps = execution_plan.get("reused_steps") or []
        generated_steps = execution_plan.get("generated_steps") or []

        for index, step in enumerate(reusable_steps, start=1):
            steps.append(
                {
                    "index": index,
                    "name": step.get("name") or f"复用步骤 {index}",
                    "source": step.get("source", "template"),
                    "requirement": step.get("requirement"),
                    "dependencies": step.get("dependencies", []),
                    "params": step.get("params", {}),
                }
            )

        offset = len(steps)
        for index, step in enumerate(generated_steps, start=1):
            steps.append(
                {
                    "index": offset + index,
                    "name": step.get("name") or f"生成步骤 {index}",
                    "source": step.get("source", "generated"),
                    "requirement": step.get("requirement"),
                    "dependencies": step.get("dependencies", []),
                    "params": step.get("params", {}),
                }
            )

        return {
            "plan_type": execution_plan.get("plan_type"),
            "steps": steps,
            "output_contract": execution_plan.get("output_contract", {}),
        }

    def _augment_step_spec_with_execution_result(
        self,
        step_spec: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        dag_steps = (
            ((result.get("dag_status") or {}).get("current_plan") or {}).get("steps")
            or []
        )
        if not isinstance(dag_steps, list) or not dag_steps:
            return step_spec

        draft_steps = step_spec.get("steps") or []
        if not isinstance(draft_steps, list):
            return step_spec

        for index, draft_step in enumerate(draft_steps):
            dag_step = dag_steps[index] if index < len(dag_steps) else None
            if not isinstance(dag_step, dict):
                continue

            tool_names = dag_step.get("tool_names") or []
            executor_type = self._infer_executor_type(
                tool_names=tool_names,
                step_name=str(dag_step.get("name") or draft_step.get("name") or ""),
                step_description=str(
                    dag_step.get("description") or draft_step.get("requirement") or ""
                ),
            )
            asset_id = self._extract_asset_id(dag_step.get("result"))

            draft_step["executor_type"] = executor_type
            draft_step["asset_id"] = asset_id
            if isinstance(dag_step.get("context"), dict) and dag_step["context"]:
                draft_step["context"] = dag_step["context"]
            if isinstance(dag_step.get("result"), dict) and dag_step["result"]:
                draft_step["result_snapshot"] = self._summarize_result(
                    dag_step["result"]
                )

        return step_spec

    def _infer_executor_type(
        self,
        *,
        tool_names: list[str],
        step_name: str,
        step_description: str,
    ) -> str:
        normalized_tools = {str(item).lower() for item in tool_names}
        if "agent_sql_executor" in normalized_tools:
            return "sql"
        if "agent_http_executor" in normalized_tools:
            return "http"
        if "agent_dubbo_executor" in normalized_tools:
            return "dubbo"
        if "agent_mcp_executor" in normalized_tools:
            return "mcp"

        probe = f"{step_name} {step_description}".lower()
        if "sql" in probe or "表" in probe or "查询" in probe:
            return "sql"
        if "http" in probe or "接口" in probe or "下载" in probe or "上传" in probe:
            return "http"
        if "dubbo" in probe:
            return "dubbo"
        if "mcp" in probe:
            return "mcp"
        return "unknown"

    def _extract_asset_id(self, payload: Any) -> int | None:
        if isinstance(payload, dict):
            if "asset_id" in payload and payload["asset_id"] is not None:
                try:
                    return int(payload["asset_id"])
                except Exception:
                    return None
            if isinstance(payload.get("asset_match"), dict):
                nested_asset = payload["asset_match"].get("asset_id")
                if nested_asset is not None:
                    try:
                        return int(nested_asset)
                    except Exception:
                        return None
            for value in payload.values():
                found = self._extract_asset_id(value)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._extract_asset_id(item)
                if found is not None:
                    return found
        return None

    def _summarize_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary_keys = [
            "success",
            "output",
            "summary",
            "status_code",
            "sql",
            "intermediate_sql",
            "downloaded_file_id",
            "extracted_fields",
            "asset_match",
        ]
        result = {}
        for key in summary_keys:
            if key in payload and payload[key] is not None:
                result[key] = payload[key]
        return result

    def _build_param_schema(self, params: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for key, value in params.items():
            if value is None:
                continue
            json_type = self._infer_json_type(value)
            properties[key] = {
                "type": json_type,
                "default": value,
                "description": f"自动提取参数：{key}",
            }
            required.append(key)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    @staticmethod
    def _infer_json_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"
