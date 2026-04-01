"""
`Template Publish Service`（模板发布服务）模块。

这个服务负责把已经通过 compile 的模板草稿冻结成可复跑版本快照。
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, sessionmaker

from ..contracts.template_pipeline import (
    CompiledDagContract,
    TemplateVersionDigest,
    TemplateVersionSnapshot,
)
from ..ledger.sql_models import (
    DataMakeApprovalState,
    DataMakeTemplateDraft,
    DataMakeTemplateRun,
    DataMakeTemplateVersion,
)


class TemplatePublishError(ValueError):
    """
    `TemplatePublishError`（模板发布异常）。

    这里把“业务上不能发布”的失败显式区分出来，
    让 Runtime 能稳定回流成结构化 failure observation，
    而不是把所有问题都混成未知异常。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TemplatePublishService:
    """
    `TemplatePublishService`（模板发布服务）。

    设计边界：
    - 输入必须是已经存在的 `TemplateDraft` 工件，而不是自由文本草稿。
    - 发布只做“冻结快照 + 落库留痕”，不代替主脑自动触发后续执行。
    - 审批相关信息只作为审计证据写入快照 metadata，不作为新的流程控制器。
    """

    def __init__(self, session_factory: sessionmaker[Session] | Any) -> None:
        self.session_factory = session_factory

    async def publish(
        self,
        *,
        template_draft_id: int,
        template_id: str | None = None,
        template_name: str | None = None,
        approval_key: str | None = None,
        publisher_user_id: str | None = None,
        publisher_user_name: str | None = None,
        publish_reason: str | None = None,
        visibility: str | None = None,
        approval_required: bool | None = None,
        approval_passed: bool | None = None,
        effect_tags: list[str] | None = None,
        env_tags: list[str] | None = None,
    ) -> TemplateVersionSnapshot:
        """
        把指定模板草稿冻结成一个新的模板版本快照。

        输入输出语义：
        - 输入是模板草稿主键与少量发布元信息。
        - 输出是已经落库后的 `TemplateVersionSnapshot`，其中包含稳定的版本号与主键。

        关键约束：
        - 若草稿不存在、compiled DAG 缺失、仍有 unresolved mappings，则必须阻断发布。
        - 发布后生成的是“冻结快照”，后续执行不得再回看活跃 `FlowDraft`。
        - 草稿状态允许更新为 `published`，但这只是工件生命周期标记，不能驱动自动执行。
        """

        with self._new_session() as session:
            draft = session.get(DataMakeTemplateDraft, template_draft_id)
            if draft is None:
                raise TemplatePublishError(
                    "template_draft_not_found",
                    "未找到要发布的模板草稿",
                )

            if not isinstance(draft.compiled_dag_json, dict):
                raise TemplatePublishError(
                    "template_draft_compiled_dag_missing",
                    "模板草稿缺少 compiled DAG，不能直接发布",
                )

            compiled = CompiledDagContract.model_validate(draft.compiled_dag_json)
            if compiled.unresolved_mappings:
                raise TemplatePublishError(
                    "template_draft_has_unresolved_mappings",
                    "模板草稿仍存在未解析映射，不能发布为可复跑模板",
                )

            resolved_template_id = self._resolve_template_id(
                explicit_template_id=template_id,
                task_id=draft.task_id,
                session=session,
            )
            next_version = self._resolve_next_version(
                template_id=resolved_template_id,
                session=session,
            )
            resolved_template_name = self._resolve_template_name(
                explicit_template_name=template_name,
                draft=draft,
                compiled=compiled,
            )
            resolved_visibility = self._resolve_visibility(visibility)
            (
                resolved_approval_required,
                resolved_approval_passed,
            ) = self._resolve_approval_flags(
                session=session,
                approval_key=approval_key,
                explicit_approval_required=approval_required,
                explicit_approval_passed=approval_passed,
            )
            resolved_env_tags = self._build_env_tags(
                draft_payload=draft.draft_json,
                explicit_env_tags=env_tags,
            )
            resolved_effect_tags = self._build_effect_tags(
                compiled=compiled,
                draft_payload=draft.draft_json,
                explicit_effect_tags=effect_tags,
            )

            version_row = DataMakeTemplateVersion(
                template_id=resolved_template_id,
                task_id=draft.task_id,
                system_short=self._coalesce_str(compiled.metadata.get("system_short")),
                entity_name=self._coalesce_str(compiled.metadata.get("entity_name")),
                executor_kind=self._coalesce_str(compiled.metadata.get("executor_kind")),
                publisher_user_id=self._coalesce_str(publisher_user_id),
                publisher_user_name=self._coalesce_str(publisher_user_name),
                visibility=resolved_visibility,
                approval_required=resolved_approval_required,
                approval_passed=resolved_approval_passed,
                effect_tags_json=resolved_effect_tags,
                env_tags_json=resolved_env_tags,
                template_draft_id=draft.id,
                version=next_version,
                status="active",
                snapshot_json={},
                summary=draft.summary or compiled.goal_summary,
            )
            session.add(version_row)
            session.flush()

            snapshot = TemplateVersionSnapshot(
                template_id=resolved_template_id,
                version=next_version,
                template_version_id=version_row.id,
                template_name=resolved_template_name,
                task_id=draft.task_id,
                goal_summary=draft.summary or compiled.goal_summary,
                compiled_dag=compiled,
                params_schema=self._build_params_schema(draft.draft_json),
                metadata={
                    "template_draft_id": draft.id,
                    "flow_draft_version": draft.flow_draft_version,
                    "compiled_dag_version": draft.compiled_dag_version,
                    "risk_level": self._resolve_risk_level(draft.draft_json),
                    "approval_key": approval_key,
                    "publisher_user_id": publisher_user_id,
                    "publisher_user_name": publisher_user_name,
                    "publish_reason": publish_reason,
                    "visibility": resolved_visibility,
                    "approval_required": resolved_approval_required,
                    "approval_passed": resolved_approval_passed,
                    "effect_tags": resolved_effect_tags,
                    "env_tags": resolved_env_tags,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            version_row.snapshot_json = snapshot.model_dump(mode="json")
            draft.status = "published"
            session.commit()
            return snapshot

    def build_digest(
        self,
        snapshot: TemplateVersionSnapshot,
        *,
        run_stats: dict[str, Any] | None = None,
    ) -> TemplateVersionDigest:
        """
        从模板版本快照生成轻量摘要。

        这个摘要主要给 observation / API / Agent 提示使用，
        避免每次都把整份 compiled DAG 快照塞回上层上下文。
        """

        run_stats = run_stats or {}
        return TemplateVersionDigest(
            template_version_id=snapshot.template_version_id,
            template_id=snapshot.template_id,
            version=snapshot.version,
            task_id=snapshot.task_id,
            template_name=snapshot.template_name,
            goal_summary=snapshot.goal_summary,
            template_draft_id=self._extract_template_draft_id(snapshot),
            step_count=len(snapshot.compiled_dag.steps),
            risk_level=self._extract_risk_level(snapshot),
            execution_success_rate=run_stats.get("success_rate"),
            recent_run_count=int(run_stats.get("recent_run_count", 0) or 0),
            last_success_run_at=run_stats.get("last_success_run_at"),
            visibility=self._extract_visibility(snapshot),
            publisher_user_id=self._extract_publisher_user_id(snapshot),
            approval_passed=self._extract_approval_passed(snapshot),
        )

    async def load_latest_digest(self, task_id: str) -> TemplateVersionDigest | None:
        """
        读取任务最近一次已发布模板版本的轻量摘要。

        这里的用途是把“当前已经存在可复跑版本”这条证据回灌给主脑，
        供它判断下一轮是继续修草稿、重新发布，还是直接复跑版本。
        它不是自动执行触发器。
        """

        with self._new_session() as session:
            row = session.execute(
                select(DataMakeTemplateVersion)
                .where(DataMakeTemplateVersion.task_id == task_id)
                .order_by(DataMakeTemplateVersion.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None or not isinstance(row.snapshot_json, dict):
                return None
            snapshot = TemplateVersionSnapshot.model_validate(row.snapshot_json)
            return self.build_digest(
                snapshot,
                run_stats=self._load_run_stats(
                    session=session,
                    template_version_id=int(row.id),
                ),
            )

    def _resolve_template_id(
        self,
        *,
        explicit_template_id: str | None,
        task_id: str,
        session: Session,
    ) -> str:
        """
        解析模板稳定标识。

        首发策略保持最小侵入：
        - 调用方显式给了 `template_id` 就优先使用。
        - 否则复用同一 `task_id` 最近已发布版本的 `template_id`，保证版本线连续。
        - 再没有历史时，退化为基于 task_id 的稳定生成值。
        """

        if isinstance(explicit_template_id, str) and explicit_template_id.strip():
            return explicit_template_id.strip()

        latest_snapshot = session.execute(
            select(DataMakeTemplateVersion.snapshot_json)
            .where(DataMakeTemplateVersion.task_id == task_id)
            .order_by(DataMakeTemplateVersion.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if isinstance(latest_snapshot, dict):
            latest_template_id = latest_snapshot.get("template_id")
            if isinstance(latest_template_id, str) and latest_template_id.strip():
                return latest_template_id.strip()

        normalized_task_id = re.sub(r"[^0-9a-zA-Z_]+", "_", task_id).strip("_")
        return f"template_{normalized_task_id or 'datamake'}"

    def _resolve_next_version(self, *, template_id: str, session: Session) -> int:
        """
        计算同一模板标识下的下一个版本号。
        """

        current_max = session.execute(
            select(func.max(DataMakeTemplateVersion.version)).where(
                DataMakeTemplateVersion.template_id == template_id
            )
        ).scalar_one()
        return int(current_max or 0) + 1

    def _resolve_template_name(
        self,
        *,
        explicit_template_name: str | None,
        draft: DataMakeTemplateDraft,
        compiled: CompiledDagContract,
    ) -> str:
        """
        解析模板展示名。

        这里的命名只影响展示和回放可读性，不参与版本线的唯一性判断。
        """

        if isinstance(explicit_template_name, str) and explicit_template_name.strip():
            return explicit_template_name.strip()
        if isinstance(draft.summary, str) and draft.summary.strip():
            return draft.summary.strip()
        if isinstance(compiled.goal_summary, str) and compiled.goal_summary.strip():
            return compiled.goal_summary.strip()
        return compiled.draft_id

    def _build_params_schema(self, draft_payload: Any) -> dict[str, Any]:
        """
        从模板草稿的参数池生成首版参数约束摘要。

        当前阶段不额外设计复杂 schema DSL，只把：
        - 参数默认值
        - 参数状态
        - 参数来源
        这些足够支撑回放和后续 UI 展示的事实冻结下来。
        """

        if not isinstance(draft_payload, dict):
            return {}

        raw_params = draft_payload.get("params")
        if not isinstance(raw_params, dict):
            return {}

        schema: dict[str, Any] = {}
        for key, item in raw_params.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(item, dict):
                continue
            schema[key] = {
                "status": item.get("status"),
                "default": item.get("value"),
                "source": item.get("source"),
                "description": item.get("description"),
            }
        return schema

    def _extract_template_draft_id(
        self,
        snapshot: TemplateVersionSnapshot,
    ) -> int | None:
        """
        从快照 metadata 中提取来源模板草稿主键。
        """

        value = snapshot.metadata.get("template_draft_id")
        return value if isinstance(value, int) else None

    def _extract_risk_level(
        self,
        snapshot: TemplateVersionSnapshot,
    ) -> str | None:
        """
        从快照 metadata 中提取发布时冻结的风险等级。
        """

        value = snapshot.metadata.get("risk_level")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_visibility(
        self,
        snapshot: TemplateVersionSnapshot,
    ) -> str | None:
        """
        从快照 metadata 中提取模板可见性。
        """

        value = snapshot.metadata.get("visibility")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_publisher_user_id(
        self,
        snapshot: TemplateVersionSnapshot,
    ) -> str | None:
        """
        从快照 metadata 中提取发布人标识。
        """

        value = snapshot.metadata.get("publisher_user_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_approval_passed(
        self,
        snapshot: TemplateVersionSnapshot,
    ) -> bool | None:
        """
        从快照 metadata 中提取审批是否明确通过。
        """

        value = snapshot.metadata.get("approval_passed")
        return value if isinstance(value, bool) else None

    def _resolve_risk_level(self, draft_payload: Any) -> str:
        """
        解析模板发布时应冻结的风险等级。
        """

        if isinstance(draft_payload, dict):
            value = draft_payload.get("latest_risk")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "low"

    def _resolve_visibility(self, visibility: str | None) -> str:
        """
        解析模板版本可见性。

        当前最小治理语义：
        - `private`：仅发布人自己优先可见
        - `shared`：对其他任务可复用，但仍然属于业务域内共享资产
        - `global`：全局可复用模板
        """

        normalized = self._coalesce_str(visibility)
        if normalized in {"private", "shared", "global"}:
            return str(normalized)
        return "global"

    def _resolve_approval_flags(
        self,
        *,
        session: Session,
        approval_key: str | None,
        explicit_approval_required: bool | None,
        explicit_approval_passed: bool | None,
    ) -> tuple[bool, bool | None]:
        """
        冻结发布时关联的审批事实。

        设计重点：
        - 审批结果在这里仅作为模板治理事实写入版本快照和宿主表。
        - 即便审批已通过，也不会在这里自动推进任何后续执行动作。
        """

        resolved_required = (
            explicit_approval_required
            if isinstance(explicit_approval_required, bool)
            else bool(self._coalesce_str(approval_key))
        )
        if isinstance(explicit_approval_passed, bool):
            return resolved_required, explicit_approval_passed

        normalized_key = self._coalesce_str(approval_key)
        if normalized_key is None:
            return resolved_required, None if resolved_required else False

        state = session.execute(
            select(DataMakeApprovalState)
            .where(DataMakeApprovalState.approval_key == normalized_key)
            .order_by(DataMakeApprovalState.resolved_at.desc(), DataMakeApprovalState.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if state is None:
            return resolved_required, False

        if state.status == "approved":
            return True, True
        if state.status == "rejected":
            return True, False

        resolved_payload = (
            state.resolved_result_json if isinstance(state.resolved_result_json, dict) else {}
        )
        approved = resolved_payload.get("approved")
        return True, approved if isinstance(approved, bool) else False

    def _build_env_tags(
        self,
        *,
        draft_payload: Any,
        explicit_env_tags: list[str] | None,
    ) -> list[str]:
        """
        生成模板版本的环境标签。

        这些标签不是新的环境状态机，只是为了检索阶段能更快识别：
        “这个模板通常在哪些环境使用过/冻结时面向哪个环境”。
        """

        tags = self._normalize_tag_list(explicit_env_tags)
        if isinstance(draft_payload, dict):
            params = draft_payload.get("params")
            if isinstance(params, dict):
                for key in ("target_environment", "environment", "env"):
                    raw_item = params.get(key)
                    if isinstance(raw_item, dict):
                        value = raw_item.get("value")
                        if isinstance(value, str) and value.strip():
                            tags.add(value.strip().lower())
        return sorted(tags)

    def _build_effect_tags(
        self,
        *,
        compiled: CompiledDagContract,
        draft_payload: Any,
        explicit_effect_tags: list[str] | None,
    ) -> list[str]:
        """
        生成模板版本的影响标签。

        这里不试图做复杂语义理解，只冻结几类稳定事实：
        - 业务域 / 实体 / 执行方式
        - DAG 中实际出现过的 step kind
        - 从 goal/step 名称里提炼出的粗粒度动作词
        """

        tags = self._normalize_tag_list(explicit_effect_tags)
        for value in (
            compiled.metadata.get("system_short"),
            compiled.metadata.get("entity_name"),
            compiled.metadata.get("executor_kind"),
        ):
            if isinstance(value, str) and value.strip():
                tags.add(value.strip().lower())

        for step in compiled.steps:
            if step.kind:
                tags.add(str(step.kind).strip().lower())
            if step.name:
                tags.update(self._extract_action_tags(step.name))

        if compiled.goal_summary:
            tags.update(self._extract_action_tags(compiled.goal_summary))

        if isinstance(draft_payload, dict):
            latest_risk = draft_payload.get("latest_risk")
            if isinstance(latest_risk, str) and latest_risk.strip():
                tags.add(f"risk:{latest_risk.strip().lower()}")

        return sorted(tags)

    def _normalize_tag_list(self, tags: list[str] | None) -> set[str]:
        """
        清洗标签列表，避免把空串或大小写噪音写进宿主表。
        """

        normalized: set[str] = set()
        if not isinstance(tags, list):
            return normalized
        for item in tags:
            if isinstance(item, str) and item.strip():
                normalized.add(item.strip().lower())
        return normalized

    def _extract_action_tags(self, text: str) -> set[str]:
        """
        从目标摘要/步骤名提炼粗粒度动作标签。
        """

        normalized = text.strip().lower()
        mapping = {
            "create": ("创建", "新增", "写入", "seed", "insert"),
            "update": ("更新", "修改", "patch", "update"),
            "delete": ("删除", "清理", "移除", "drop", "delete", "remove"),
            "query": ("查询", "读取", "检索", "select", "query", "read"),
            "publish": ("发布", "publish"),
        }
        tags: set[str] = set()
        for tag, keywords in mapping.items():
            if any(keyword in normalized for keyword in keywords):
                tags.add(tag)
        return tags

    def _coalesce_str(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _load_run_stats(
        self,
        *,
        session: Session,
        template_version_id: int,
    ) -> dict[str, Any]:
        """
        读取单个模板版本最近执行统计。
        """

        rows = session.execute(
            select(DataMakeTemplateRun)
            .where(DataMakeTemplateRun.template_version_id == template_version_id)
            .order_by(desc(DataMakeTemplateRun.id))
            .limit(10)
        ).scalars().all()
        if not rows:
            return {}

        success_rows = [row for row in rows if row.status == "success"]
        last_success = next((row.created_at for row in rows if row.status == "success"), None)
        return {
            "recent_run_count": len(rows),
            "success_rate": round(len(success_rows) / len(rows), 4),
            "last_success_run_at": last_success,
        }

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("TemplatePublishService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
