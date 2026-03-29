"""智能造数平台 Probe 服务。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from xagent.datamakepool.sql_brain.execution_probe import SqlExecutionProbe
from xagent.datamakepool.sql_brain.models import SqlExecutionProbeTarget
from xagent.datamakepool.probe import (
    FlowDraftProbeDraftApplier,
    FlowDraftProbePlanner,
    ProbeFindingNormalizer,
)
from xagent.datamakepool.templates import TemplateService
from xagent.web.models.datamakepool_asset import DataMakepoolAsset
from xagent.web.models.datamakepool_conversation import DataMakepoolConversationSession
from xagent.web.models.datamakepool_probe import DataMakepoolProbeRun
from .flow_draft_service import FlowDraftService
from .runtime_service import ConversationRuntimeService


class ProbeService:
    """封装会话里的局部试跑能力。

    当前阶段支持：
    - SQL 资产 dry-run
    - HTTP 资产 preview
    - Template preview

    后续再补：
    - HTTP dry-run / sample response
    - Dubbo probe
    """

    def __init__(self, db: Session):
        self._db = db
        self._template_service = TemplateService(db)
        self._runtime = ConversationRuntimeService(db)
        self._flow_draft_service = FlowDraftService(db)
        self._planner = FlowDraftProbePlanner()
        self._normalizer = ProbeFindingNormalizer()
        self._draft_applier = FlowDraftProbeDraftApplier(self._flow_draft_service)

    def run_probe(
        self,
        *,
        session: DataMakepoolConversationSession,
        probe_type: str | None,
        target_ref: str | None,
        payload: dict[str, Any] | None = None,
        mode: str = "preview",
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        active_draft = None
        if getattr(session, "active_flow_draft_id", None) is not None:
            active_draft = self._flow_draft_service.get_draft_by_id(
                int(session.active_flow_draft_id)
            )
        planned_probe = self._planner.plan(
            draft=active_draft,
            preferred_probe_type=probe_type,
            preferred_target_ref=target_ref,
            mode=mode,
        )
        if planned_probe is None:
            return {
                "success": False,
                "summary": "当前没有可执行的 probe 目标",
                "message": "当前草稿里还没有可执行的 probe 目标，请先完成候选选择或补齐关键参数。",
                "raw_result": {
                    "requested_probe_type": probe_type,
                    "requested_target_ref": target_ref,
                },
                "ui": {
                    "type": "probe_result",
                    "message": "当前草稿里还没有可执行的 probe 目标，请先完成候选选择或补齐关键参数。",
                    "data": {
                        "probe_type": probe_type,
                        "target_ref": target_ref,
                    },
                },
            }
        probe_type = str(planned_probe.probe_type).strip().lower()
        target_ref = str(planned_probe.target_ref)
        run = self._runtime.create_execution_run(
            session=session,
            task_id=int(session.task_id),
            run_type="probe",
            trigger_event_type="USER_REQUEST_PROBE",
            linked_draft_id=(
                int(session.active_flow_draft_id)
                if getattr(session, "active_flow_draft_id", None) is not None
                else None
            ),
            target_ref=target_ref,
            input_payload={
                "probe_type": probe_type,
                "mode": planned_probe.mode,
                "payload": payload,
            },
        )

        if probe_type == "sql_asset":
            result = self._probe_sql_asset(target_ref=target_ref, payload=payload, mode=mode)
        elif probe_type == "http_asset":
            result = self._probe_http_asset(target_ref=target_ref, payload=payload, mode=mode)
        elif probe_type == "template":
            result = self._probe_template(target_ref=target_ref, payload=payload, mode=mode)
        else:
            result = {
                "success": False,
                "summary": f"暂不支持的 probe 类型: {probe_type}",
                "raw_result": {"probe_type": probe_type, "target_ref": target_ref},
                "findings": ["unsupported_probe_type"],
                "message": f"当前版本暂不支持 {probe_type} 类型的试跑。",
            }

        row = DataMakepoolProbeRun(
            session_id=int(session.id),
            probe_type=probe_type,
            target_ref=target_ref,
            mode=mode,
            success="success" if result.get("success") else "failed",
            input_payload=payload,
            raw_result=result.get("raw_result"),
            findings=result.get("findings"),
            result_summary=result.get("summary"),
            user_visible_message=result.get("message"),
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)

        feedback = self._normalizer.normalize(
            session=session,
            planned_probe=planned_probe,
            result=result,
            probe_run_id=int(row.id),
        )
        active_draft_id = (
            int(session.active_flow_draft_id)
            if getattr(session, "active_flow_draft_id", None) is not None
            else None
        )
        self._draft_applier.apply(draft_id=active_draft_id, feedback=feedback)

        session.state = "clarifying"
        session.latest_summary = str(result.get("summary") or "")
        self._db.add(session)
        self._db.commit()
        self._runtime.finish_execution_run(
            run_id=int(run.id),
            status="completed" if result.get("success") else "failed",
            summary=str(result.get("summary") or ""),
            result_payload={
                "probe_run_id": int(row.id),
                "probe_type": probe_type,
                "raw_result": result.get("raw_result"),
                "findings": result.get("findings"),
            },
        )

        return {
            "execution_run_id": int(run.id),
            "probe_run_id": int(row.id),
            "success": bool(result.get("success")),
            "summary": result.get("summary"),
            "message": result.get("message"),
            "raw_result": result.get("raw_result"),
            "ui": {
                "type": "probe_result",
                "message": result.get("message"),
                "data": {
                    "probe_run_id": int(row.id),
                    "probe_type": probe_type,
                    "target_ref": target_ref,
                    "reason": planned_probe.reason,
                    "summary": result.get("summary"),
                    "raw_result": result.get("raw_result"),
                    "findings": result.get("findings") or [],
                },
            },
        }

    def _probe_sql_asset(
        self,
        *,
        target_ref: str,
        payload: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        asset_id = self._extract_numeric_id(target_ref, prefix="sql:")
        if asset_id is None:
            return {
                "success": False,
                "summary": "SQL 资产标识不合法",
                "raw_result": {"target_ref": target_ref},
                "findings": ["invalid_sql_asset_id"],
                "message": f"无法识别 SQL 资产标识：{target_ref}",
            }

        asset = self._db.query(DataMakepoolAsset).filter(DataMakepoolAsset.id == asset_id).first()
        if asset is None or asset.asset_type != "sql":
            return {
                "success": False,
                "summary": "SQL 资产不存在",
                "raw_result": {"asset_id": asset_id},
                "findings": ["sql_asset_not_found"],
                "message": f"SQL 资产 {asset_id} 不存在或类型不正确。",
            }

        datasource_id = getattr(asset, "datasource_asset_id", None)
        datasource = None
        if datasource_id:
            datasource = (
                self._db.query(DataMakepoolAsset)
                .filter(DataMakepoolAsset.id == int(datasource_id))
                .first()
            )
        if datasource is None or datasource.asset_type != "datasource":
            return {
                "success": False,
                "summary": "SQL 资产缺少数据源",
                "raw_result": {"asset_id": asset_id, "datasource_asset_id": datasource_id},
                "findings": ["sql_asset_missing_datasource"],
                "message": f"SQL 资产 {asset_id} 缺少可探测的数据源配置。",
            }

        sql_template = str((asset.config or {}).get("sql_template") or "").strip()
        rendered_sql = self._render_sql_template(sql_template, payload)
        unresolved = self._find_unresolved_placeholders(rendered_sql)
        if unresolved:
            return {
                "success": False,
                "summary": "SQL probe 缺少参数",
                "raw_result": {
                    "asset_id": asset_id,
                    "sql_template": sql_template,
                    "rendered_sql": rendered_sql,
                    "missing_params": unresolved,
                },
                "findings": unresolved,
                "message": "SQL 试跑前仍缺少参数："
                + "、".join(sorted(set(unresolved))),
            }

        probe = SqlExecutionProbe()
        target = SqlExecutionProbeTarget(
            db_url=str((datasource.config or {}).get("url") or ""),
            db_type=str((datasource.config or {}).get("db_type") or "") or None,
            source=f"datasource_asset:{int(datasource.id)}",
        )
        probe_result = probe.probe_sql(sql=rendered_sql, target=target, mode="dry_run")
        summary = (
            "SQL 试跑成功：语法、连接、对象存在性已通过 dry-run 检查。"
            if probe_result.ok
            else f"SQL 试跑失败：{probe_result.error or probe_result.message}"
        )
        return {
            "success": probe_result.ok,
            "summary": summary,
            "raw_result": {
                "asset_id": asset_id,
                "asset_name": asset.name,
                "datasource_asset_id": int(datasource.id),
                "sql": rendered_sql,
                "probe_sql": probe_result.probe_sql,
                "execution_mode": probe_result.execution_mode,
                "message": probe_result.message,
                "error": probe_result.error,
            },
            "findings": [] if probe_result.ok else [probe_result.error or "probe_failed"],
            "message": summary,
        }

    def _probe_http_asset(
        self,
        *,
        target_ref: str,
        payload: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        del mode
        asset_id = self._extract_numeric_id(target_ref, prefix="http:")
        if asset_id is None:
            return {
                "success": False,
                "summary": "HTTP 资产标识不合法",
                "raw_result": {"target_ref": target_ref},
                "findings": ["invalid_http_asset_id"],
                "message": f"无法识别 HTTP 资产标识：{target_ref}",
            }
        asset = self._db.query(DataMakepoolAsset).filter(DataMakepoolAsset.id == asset_id).first()
        if asset is None or asset.asset_type != "http":
            return {
                "success": False,
                "summary": "HTTP 资产不存在",
                "raw_result": {"asset_id": asset_id},
                "findings": ["http_asset_not_found"],
                "message": f"HTTP 资产 {asset_id} 不存在或类型不正确。",
            }
        config = dict(asset.config or {})
        preview = {
            "asset_id": asset_id,
            "asset_name": asset.name,
            "method": config.get("method"),
            "base_url": config.get("base_url"),
            "path_template": config.get("path_template"),
            "path_preview": self._render_sql_template(
                str(config.get("path_template") or ""), payload
            ),
        }
        return {
            "success": True,
            "summary": "HTTP probe 已生成请求预览，当前版本默认不直接外呼。",
            "raw_result": preview,
            "findings": [],
            "message": "HTTP 试跑预览已生成。请确认 method、path 和参数替换结果是否符合预期。",
        }

    def _probe_template(
        self,
        *,
        target_ref: str,
        payload: dict[str, Any],
        mode: str,
    ) -> dict[str, Any]:
        del payload, mode
        template_id = self._extract_numeric_id(target_ref, prefix="template:")
        if template_id is None:
            return {
                "success": False,
                "summary": "模板标识不合法",
                "raw_result": {"target_ref": target_ref},
                "findings": ["invalid_template_id"],
                "message": f"无法识别模板标识：{target_ref}",
            }
        template = self._template_service.get_template(template_id)
        if template is None:
            return {
                "success": False,
                "summary": "模板不存在",
                "raw_result": {"template_id": template_id},
                "findings": ["template_not_found"],
                "message": f"模板 {template_id} 不存在。",
            }
        spec = self._template_service.get_template_execution_spec(
            template_id,
            version=int(template.get("current_version") or 1),
        ) or {}
        steps = spec.get("step_spec") or []
        raw_result = {
            "template_id": template_id,
            "template_name": template.get("name"),
            "version": template.get("current_version"),
            "system_short": template.get("system_short"),
            "param_schema": spec.get("param_schema") or spec.get("param_schema_snapshot"),
            "step_count": len(steps),
            "step_names": [
                str(step.get("name") or step.get("step_name") or f"step_{idx + 1}")
                for idx, step in enumerate(steps)
                if isinstance(step, dict)
            ],
        }
        return {
            "success": True,
            "summary": f"模板预览完成，共 {raw_result['step_count']} 个步骤。",
            "raw_result": raw_result,
            "findings": [],
            "message": "模板预览已生成。你可以先确认参数要求和步骤结构，再决定是否正式执行。",
        }

    @staticmethod
    def _extract_numeric_id(target_ref: str, *, prefix: str) -> int | None:
        raw = str(target_ref or "").strip()
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
        try:
            return int(raw)
        except Exception:
            return None

    @staticmethod
    def _render_sql_template(template: str, payload: dict[str, Any]) -> str:
        rendered = str(template or "")
        for key, value in payload.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered

    @staticmethod
    def _find_unresolved_placeholders(sql: str) -> list[str]:
        matches = re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", sql or "")
        return [str(item) for item in matches]
