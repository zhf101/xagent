"""模板直执行器。

这层执行器只负责“命中模板后的真实执行”：
- 先预检模板步骤是否具备安全直跑条件
- 真实执行 HTTP / SQL 安全子集
- 把 run / step 账本按真实状态写入数据库

明确不做的事：
- 不替 orchestrator 做动态补全
- 不伪装执行 Dubbo / MCP / 未知步骤
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from xagent.core.database.adapters import create_adapter_for_type
from xagent.core.database.config import database_connection_config_from_url
from xagent.core.workspace import TaskWorkspace
from xagent.datamakepool.http_execution import HttpExecutionService, HttpRequestSpec
from xagent.datamakepool.interceptors import check_sql_needs_approval
from xagent.datamakepool.interpreter.template_matcher import MatchedTemplate
from xagent.datamakepool.templates.service import TemplateService
from xagent.web.models.datamakepool_asset import DataMakepoolAsset
from xagent.web.models.datamakepool_run import (
    DataMakepoolRun,
    DataMakepoolRunStep,
    RunStatus,
    RunType,
    StepStatus,
)

_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}|\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}|\{([a-zA-Z_][a-zA-Z0-9_]*)\}"
)


@dataclass
class TemplateRunExecutionResult:
    success: bool
    run_id: int | None
    template_id: int
    version: int
    step_count: int
    output: str
    metadata: dict[str, Any]


@dataclass
class TemplateDirectExecutionSupport:
    executable: bool
    reason: str | None = None
    step_count: int = 0
    unsupported_steps: list[dict[str, Any]] = field(default_factory=list)
    prepared_steps: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "reason": self.reason,
            "step_count": self.step_count,
            "unsupported_steps": self.unsupported_steps,
        }


class TemplateStepExecutionError(RuntimeError):
    def __init__(self, message: str, *, output_data: Any = None):
        super().__init__(message)
        self.output_data = output_data


class TemplateRunExecutor:
    """命中模板后直接执行，不走 agent。

    设计边界：
    - `analyze_match` 只回答“这份模板现在能不能直跑”
    - `execute_match` 只在预检通过后执行，并把运行态账本写完整
    """

    def __init__(self, db: Session, *, workspace: TaskWorkspace | None = None):
        self._db = db
        self._template_service = TemplateService(db)
        self._workspace = workspace
        if self._workspace is not None:
            self._workspace.db_session = db

    def analyze_match(
        self,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> TemplateDirectExecutionSupport:
        spec = self._template_service.get_template_execution_spec(matched.template_id)
        steps = self._normalize_step_spec((spec or {}).get("step_spec"))
        if not steps:
            return TemplateDirectExecutionSupport(
                executable=False,
                reason="template_has_no_executable_steps",
                step_count=0,
                unsupported_steps=[
                    {
                        "step_order": 0,
                        "step_name": "template",
                        "reason": "模板没有可执行步骤",
                    }
                ],
            )

        prepared_steps: list[dict[str, Any]] = []
        unsupported_steps: list[dict[str, Any]] = []
        for step in steps:
            try:
                prepared_steps.append(self._prepare_step(step, params))
            except Exception as exc:
                unsupported_steps.append(
                    {
                        "step_order": int(step["order"]),
                        "step_name": str(step["name"]),
                        "reason": str(exc),
                    }
                )

        return TemplateDirectExecutionSupport(
            executable=not unsupported_steps,
            reason=(unsupported_steps[0]["reason"] if unsupported_steps else "ok"),
            step_count=len(steps),
            unsupported_steps=unsupported_steps,
            prepared_steps=prepared_steps,
        )

    async def execute_match(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> TemplateRunExecutionResult:
        support = self.analyze_match(matched, params)
        if not support.executable:
            return TemplateRunExecutionResult(
                success=False,
                run_id=None,
                template_id=matched.template_id,
                version=matched.version,
                step_count=support.step_count,
                output=f"模板「{matched.template_name}」无法走模板直跑：{support.reason}",
                metadata={
                    "execution_type": "datamakepool_template_run",
                    "template_id": matched.template_id,
                    "template_version": matched.version,
                    "step_count": support.step_count,
                    "direct_execution_supported": False,
                    "run_id": None,
                    "unsupported_steps": support.unsupported_steps,
                },
            )

        run_id = self._create_run(task_id, created_by, matched, params)
        step_results: list[dict[str, Any]] = []
        for prepared in support.prepared_steps:
            step_id = self._create_step(run_id, prepared, matched, params)
            try:
                self._update_step(
                    step_id, status="running", started_at=datetime.now(timezone.utc)
                )
                payload = await self._execute_step(prepared)
                self._update_step(
                    step_id,
                    status="completed",
                    output_data=self._json_safe(payload),
                    finished_at=datetime.now(timezone.utc),
                    error_message=None,
                )
                step_results.append(
                    self._step_summary(
                        prepared, True, payload.get("summary") or payload.get("output")
                    )
                )
            except Exception as exc:
                payload = (
                    exc.output_data
                    if isinstance(exc, TemplateStepExecutionError)
                    else {"success": False, "error": str(exc)}
                )
                self._update_step(
                    step_id,
                    status="failed",
                    output_data=self._json_safe(payload),
                    finished_at=datetime.now(timezone.utc),
                    error_message=str(exc),
                )
                self._update_run(run_id, "failed", None, str(exc))
                step_results.append(self._step_summary(prepared, False, str(exc)))
                return TemplateRunExecutionResult(
                    success=False,
                    run_id=run_id,
                    template_id=matched.template_id,
                    version=matched.version,
                    step_count=support.step_count,
                    output=f"模板直执行失败：步骤「{prepared['name']}」失败，原因：{exc}",
                    metadata={
                        "execution_type": "datamakepool_template_run",
                        "template_id": matched.template_id,
                        "template_version": matched.version,
                        "run_id": run_id,
                        "step_results": step_results,
                    },
                )

        self._update_run(
            run_id,
            "completed",
            f"模板「{matched.template_name}」已完成 {len(step_results)} 个真实执行步骤。",
            None,
        )
        self._increment_used_count(matched.template_id)
        return TemplateRunExecutionResult(
            success=True,
            run_id=run_id,
            template_id=matched.template_id,
            version=matched.version,
            step_count=support.step_count,
            output=f"已命中模板「{matched.template_name}」并完成 {len(step_results)} 个真实执行步骤。",
            metadata={
                "execution_type": "datamakepool_template_run",
                "template_id": matched.template_id,
                "template_version": matched.version,
                "run_id": run_id,
                "step_results": step_results,
            },
        )

    def _normalize_step_spec(self, raw_step_spec: Any) -> list[dict[str, Any]]:
        if isinstance(raw_step_spec, dict):
            candidate_steps = (
                raw_step_spec.get("steps") or raw_step_spec.get("step_spec") or []
            )
        elif isinstance(raw_step_spec, list):
            candidate_steps = raw_step_spec
        else:
            candidate_steps = []
        steps: list[dict[str, Any]] = []
        for index, item in enumerate(candidate_steps, start=1):
            if not isinstance(item, dict):
                continue
            step = dict(item)
            step["order"] = int(step.get("index") or step.get("step_order") or index)
            step["name"] = str(
                step.get("name") or step.get("step_name") or f"step_{index}"
            )
            steps.append(step)
        return steps

    def _prepare_step(
        self, step: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        asset = self._resolve_asset(step.get("asset_id"))
        kind = self._infer_kind(step, asset)
        if kind == "http":
            spec = self._build_http_spec(step, params, asset)
            if spec.download.enabled and self._workspace is None:
                raise ValueError("http_download_requires_workspace")
            return {
                "order": int(step["order"]),
                "name": str(step["name"]),
                "kind": "http",
                "asset_id": int(asset.id) if asset is not None else None,
                "asset_snapshot": self._asset_snapshot(asset),
                "approval_policy": str(step.get("approval_policy") or "none"),
                "input_data": {"request_spec": self._json_safe(spec.model_dump())},
                "http_spec": spec,
            }
        if kind == "sql":
            if asset is None or asset.asset_type != "sql":
                raise ValueError("sql_step_requires_governed_sql_asset")
            sql = str(
                step.get("sql")
                or step.get("sql_template")
                or (asset.config or {}).get("sql_template")
                or ""
            ).strip()
            sql = str(self._render_value(sql, params)).strip()
            if not sql:
                raise ValueError("sql_step_missing_sql_template")
            if self._has_placeholder(sql):
                raise ValueError("sql_step_has_unresolved_placeholders")
            requires_approval, approval_reason = check_sql_needs_approval(sql)
            if requires_approval:
                raise ValueError(f"sql_requires_approval:{approval_reason}")
            datasource_asset = self._resolve_datasource_asset(
                self._coerce_int(step.get("datasource_asset_id"))
                or self._coerce_int(asset.datasource_asset_id)
            )
            if datasource_asset is None:
                raise ValueError("sql_step_missing_datasource_asset")
            datasource_config = datasource_asset.config or {}
            db_url = str(datasource_config.get("url") or "").strip()
            db_type = str(datasource_config.get("db_type") or "").strip().lower()
            if not db_url or not db_type:
                raise ValueError("sql_step_invalid_datasource_config")
            return {
                "order": int(step["order"]),
                "name": str(step["name"]),
                "kind": "sql",
                "asset_id": int(asset.id),
                "asset_snapshot": self._asset_snapshot(asset),
                "approval_policy": str(
                    step.get("approval_policy")
                    or (asset.config or {}).get("approval_policy")
                    or "none"
                ),
                "input_data": {
                    "sql": sql,
                    "datasource_asset_id": int(datasource_asset.id),
                },
                "sql": sql,
                "db_url": db_url,
                "db_type": db_type,
            }
        if kind == "dubbo":
            raise ValueError("dubbo_step_not_supported_for_template_direct")
        if kind == "mcp":
            raise ValueError("mcp_step_not_supported_for_template_direct")
        raise ValueError("unknown_step_not_supported_for_template_direct")

    async def _execute_step(self, prepared: dict[str, Any]) -> dict[str, Any]:
        if prepared["kind"] == "http":
            spec: HttpRequestSpec = prepared["http_spec"]
            result = await HttpExecutionService(workspace=self._workspace).execute(spec)
            payload = self._json_safe(result.model_dump())
            payload["output"] = (
                f"HTTP {spec.method} {spec.url} -> {result.status_code}"
                if result.success
                else f"HTTP execution failed: {result.error}"
            )
            if result.summary:
                payload["summary"] = result.summary
            if not result.success:
                raise TemplateStepExecutionError(
                    result.error or f"HTTP {result.status_code}", output_data=payload
                )
            return payload

        if prepared["kind"] == "sql":
            adapter = None
            try:
                config = database_connection_config_from_url(
                    make_url(prepared["db_url"]), read_only=True
                )
                adapter = create_adapter_for_type(prepared["db_type"], config)
                await adapter.connect()
                result = await adapter.execute_query(prepared["sql"])
                return {
                    "success": True,
                    "sql": prepared["sql"],
                    "rows": self._json_safe(result.rows),
                    "row_count": len(result.rows),
                    "affected_rows": result.affected_rows,
                    "execution_time_ms": result.execution_time_ms,
                    "metadata": self._json_safe(result.metadata or {}),
                    "output": f"SQL executed successfully, returned {len(result.rows)} rows.",
                    "summary": f"SQL returned {len(result.rows)} rows.",
                }
            except Exception as exc:
                raise TemplateStepExecutionError(str(exc)) from exc
            finally:
                if adapter is not None:
                    try:
                        await adapter.disconnect()
                    except Exception:
                        pass

        raise RuntimeError(f"unsupported executor kind: {prepared['kind']}")

    def _resolve_asset(self, asset_id: Any) -> DataMakepoolAsset | None:
        normalized = self._coerce_int(asset_id)
        if normalized is None:
            return None
        return (
            self._db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == normalized)
            .first()
        )

    def _resolve_datasource_asset(
        self, asset_id: int | None
    ) -> DataMakepoolAsset | None:
        if asset_id is None:
            return None
        asset = self._resolve_asset(asset_id)
        if asset is None or asset.asset_type != "datasource":
            return None
        return asset

    def _infer_kind(self, step: dict[str, Any], asset: DataMakepoolAsset | None) -> str:
        for key in ("executor_type", "execution_source_type", "source_type", "kind"):
            value = str(step.get(key) or "").strip().lower()
            if value in {"http", "sql", "dubbo", "mcp"}:
                return value
        if asset is not None and asset.asset_type in {"http", "sql", "dubbo"}:
            return str(asset.asset_type)
        if any(
            key in step
            for key in ("request_spec_json", "request_spec", "http_request", "url")
        ):
            return "http"
        if any(key in step for key in ("sql", "sql_template", "datasource_asset_id")):
            return "sql"
        if any(key in step for key in ("service_interface", "method_name", "registry")):
            return "dubbo"
        return "unknown"

    def _build_http_spec(
        self,
        step: dict[str, Any],
        params: dict[str, Any],
        asset: DataMakepoolAsset | None,
    ) -> HttpRequestSpec:
        payload = self._extract_http_payload(step, params)
        asset_config = (
            self._json_safe(self._render_value(asset.config or {}, params))
            if asset is not None and asset.asset_type == "http"
            else {}
        )
        if not payload.get("url") and asset_config:
            base_url = str(asset_config.get("base_url") or "").rstrip("/")
            path_template = str(asset_config.get("path_template") or "").strip()
            if not base_url or not path_template:
                raise ValueError(
                    "http asset config must include base_url and path_template"
                )
            payload["url"] = f"{base_url}/{path_template.lstrip('/')}"
        if not payload.get("method") and asset_config.get("method"):
            payload["method"] = str(asset_config.get("method") or "").upper()
        payload["headers"] = {
            **(asset_config.get("default_headers") or {}),
            **(payload.get("headers") or {}),
        }
        payload["query_params"] = {
            **(asset_config.get("query_params") or {}),
            **(payload.get("query_params") or {}),
        }
        payload["form_fields"] = {
            **(asset_config.get("form_fields") or {}),
            **(payload.get("form_fields") or {}),
        }
        if (
            payload.get("json_body") is None
            and asset_config.get("json_body") is not None
        ):
            payload["json_body"] = asset_config.get("json_body")
        if not payload.get("auth_type") and asset_config.get("auth_type"):
            payload["auth_type"] = asset_config.get("auth_type")
        if not payload.get("auth_token") and asset_config.get("auth_token"):
            payload["auth_token"] = asset_config.get("auth_token")
        payload["response_extract"] = {
            **(asset_config.get("response_extract") or {}),
            **(payload.get("response_extract") or {}),
        }
        if not payload.get("download") and asset_config.get("download"):
            payload["download"] = asset_config.get("download")
        if self._contains_placeholder(payload):
            raise ValueError("http request spec still contains unresolved placeholders")
        try:
            return HttpRequestSpec.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    def _extract_http_payload(
        self, step: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        if step.get("request_spec_json"):
            rendered_json = str(
                self._render_value(str(step["request_spec_json"]), params)
            )
            parsed = json.loads(rendered_json)
            if not isinstance(parsed, dict):
                raise ValueError("request_spec_json must decode to an object")
            return self._json_safe(parsed)
        for key in ("request_spec", "http_request", "http_spec"):
            if isinstance(step.get(key), dict):
                return self._json_safe(self._render_value(step[key], params))
        direct_payload = {
            key: step[key]
            for key in (
                "url",
                "method",
                "headers",
                "query_params",
                "json_body",
                "form_fields",
                "raw_body",
                "file_parts",
                "auth_type",
                "auth_token",
                "api_key_param",
                "timeout",
                "retry_count",
                "allow_redirects",
                "download",
                "response_extract",
            )
            if key in step
        }
        return self._json_safe(self._render_value(direct_payload, params))

    def _create_run(
        self,
        task_id: int,
        created_by: int,
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> int | None:
        if not self._ledger_available():
            return None
        run = DataMakepoolRun(
            task_id=task_id,
            run_type=RunType.TEMPLATE_RUN.value,
            status=RunStatus.RUNNING.value,
            system_short=matched.system_short or params.get("system_short"),
            template_id=matched.template_id,
            template_version=matched.version,
            input_params=self._json_safe(params),
            created_by=created_by,
            started_at=datetime.now(timezone.utc),
        )
        self._db.add(run)
        self._db.commit()
        self._db.refresh(run)
        return int(run.id)

    def _create_step(
        self,
        run_id: int | None,
        prepared: dict[str, Any],
        matched: MatchedTemplate,
        params: dict[str, Any],
    ) -> int | None:
        if run_id is None or not self._ledger_available():
            return None
        step = DataMakepoolRunStep(
            run_id=run_id,
            step_order=prepared["order"],
            step_name=prepared["name"],
            asset_id=prepared.get("asset_id"),
            asset_snapshot=self._json_safe(prepared.get("asset_snapshot")),
            system_short=matched.system_short or params.get("system_short"),
            execution_source_type=prepared["kind"],
            approval_policy=prepared.get("approval_policy"),
            status=StepStatus.PENDING.value,
            input_data=self._json_safe(prepared.get("input_data")),
        )
        self._db.add(step)
        self._db.commit()
        self._db.refresh(step)
        return int(step.id)

    def _update_step(
        self,
        step_id: int | None,
        *,
        status: str,
        output_data: Any = None,
        error_message: str | None = None,
        started_at: Any = None,
        finished_at: Any = None,
    ) -> None:
        if step_id is None or not self._ledger_available():
            return
        step = self._db.get(DataMakepoolRunStep, step_id)
        if step is None:
            return
        step.status = status
        if output_data is not None:
            step.output_data = self._json_safe(output_data)
        step.error_message = error_message
        if started_at is not None:
            step.started_at = started_at
        if finished_at is not None:
            step.finished_at = finished_at
        self._db.commit()

    def _update_run(
        self,
        run_id: int | None,
        status: str,
        result_summary: str | None,
        error_message: str | None,
    ) -> None:
        if run_id is None or not self._ledger_available():
            return
        run = self._db.get(DataMakepoolRun, run_id)
        if run is None:
            return
        run.status = status
        run.result_summary = result_summary
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        self._db.commit()

    def _increment_used_count(self, template_id: int) -> None:
        try:
            if "template_stats" not in set(
                inspect(self._db.get_bind()).get_table_names()
            ):
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

    def _ledger_available(self) -> bool:
        tables = set(inspect(self._db.get_bind()).get_table_names())
        return "datamakepool_runs" in tables and "datamakepool_run_steps" in tables

    def _step_summary(
        self, prepared: dict[str, Any], success: bool, summary: str | None
    ) -> dict[str, Any]:
        return {
            "step_order": prepared["order"],
            "step_name": prepared["name"],
            "executor_type": prepared["kind"],
            "success": success,
            "summary": summary,
            "asset_id": prepared.get("asset_id"),
        }

    def _asset_snapshot(self, asset: DataMakepoolAsset | None) -> dict[str, Any] | None:
        if asset is None:
            return None
        return {
            "id": int(asset.id),
            "name": asset.name,
            "asset_type": asset.asset_type,
            "system_short": asset.system_short,
            "status": asset.status,
            "version": asset.version,
            "config": self._json_safe(asset.config or {}),
        }

    def _render_value(self, value: Any, params: dict[str, Any]) -> Any:
        if isinstance(value, str):
            rendered = value
            for key, param_value in params.items():
                replacement = "" if param_value is None else str(param_value)
                rendered = (
                    rendered.replace(f"{{{{{key}}}}}", replacement)
                    .replace(f"${{{key}}}", replacement)
                    .replace(f"{{{key}}}", replacement)
                )
            return rendered
        if isinstance(value, dict):
            return {k: self._render_value(v, params) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_value(item, params) for item in value]
        return value

    def _contains_placeholder(self, value: Any) -> bool:
        if isinstance(value, str):
            return self._has_placeholder(value)
        if isinstance(value, dict):
            return any(self._contains_placeholder(v) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_placeholder(item) for item in value)
        return False

    @staticmethod
    def _has_placeholder(value: str) -> bool:
        return bool(_PLACEHOLDER_RE.search(value))

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            return None if value in (None, "") else int(value)
        except Exception:
            return None

    def _json_safe(self, payload: Any) -> Any:
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            return payload
