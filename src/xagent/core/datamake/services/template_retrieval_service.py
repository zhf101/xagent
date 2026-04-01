"""
`Template Retrieval Service`（模板检索服务）模块。

这个服务负责从已发布模板版本里找出“当前任务可能可复用”的候选。
"""

from __future__ import annotations

import hashlib
import math
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Generator

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ...model.embedding.base import BaseEmbedding
from ..contracts.template_pipeline import (
    TemplateCandidateDigest,
    TemplateVersionSnapshot,
)
from ..ledger.sql_models import DataMakeTemplateRun, DataMakeTemplateVersion
from .models import FlowDraftAggregate
from .template_embedding_resolver import resolve_template_embedding_from_env


class TemplateRetrievalService:
    """
    `TemplateRetrievalService`（模板检索服务）。

    设计边界：
    - 只负责从已发布模板版本中找候选并给出命中理由。
    - 不自动决定最终使用哪个模板，不触发执行，也不改变任何状态。
    - 当前首版采用规则检索与打分，后续可替换为向量召回或混合检索，
      但输出边界保持不变。
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session] | Any,
        *,
        embedding_model: BaseEmbedding | None = None,
        embedding_provider: Callable[[str], list[float] | None] | None = None,
        score_weights: dict[str, float] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_model = (
            embedding_model
            if embedding_model is not None
            else resolve_template_embedding_from_env()
        )
        self.embedding_provider = embedding_provider
        self.score_weights = {
            "semantic": 3.0,
            "lexical": 0.4,
            "ownership": 1.6,
            "shared_visibility": 0.6,
            "global_visibility": 0.3,
            "approval_passed": 0.8,
            "approval_missing": -0.8,
            "env_tag": 0.8,
            "effect_tag": 0.3,
        }
        if isinstance(score_weights, dict):
            self.score_weights.update(
                {
                    key: float(value)
                    for key, value in score_weights.items()
                    if isinstance(value, (int, float))
                }
            )

    async def search_candidates(
        self,
        *,
        task: str,
        flow_draft: dict[str, Any] | FlowDraftAggregate | None,
        current_user_id: str | None = None,
        limit: int = 3,
        scan_limit: int = 50,
    ) -> list[TemplateCandidateDigest]:
        """
        从最近已发布模板版本里检索候选。

        当前策略分三步：
        1. 从数据库读取最近若干条模板版本快照
        2. 用当前 task + flow_draft 做规则打分
        3. 返回 topN 候选摘要和命中原因

        这里故意不把全量模板塞给主脑，避免模板库变大后 prompt 失控。
        """

        aggregate = self._normalize_flow_draft(flow_draft)
        if limit <= 0:
            return []

        with self._new_session() as session:
            rows = self._select_candidate_rows(
                session=session,
                aggregate=aggregate,
                current_user_id=current_user_id,
                scan_limit=scan_limit,
            )
            run_stats = self._load_run_stats(
                session=session,
                template_version_ids=[
                    int(row.id)
                    for row in rows
                    if getattr(row, "id", None) is not None
                ],
            )

        candidates: list[TemplateCandidateDigest] = []
        for row in rows:
            if not isinstance(row.snapshot_json, dict):
                continue
            snapshot = TemplateVersionSnapshot.model_validate(row.snapshot_json)
            candidate = self._score_snapshot(
                row=row,
                snapshot=snapshot,
                task=task,
                aggregate=aggregate,
                current_user_id=current_user_id,
                run_stats=run_stats.get(int(row.id), {}),
            )
            if candidate is not None:
                candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item.score,
                item.version,
                item.template_version_id or 0,
            ),
            reverse=True,
        )
        return candidates[:limit]

    def _select_candidate_rows(
        self,
        *,
        session: Session,
        aggregate: FlowDraftAggregate | None,
        current_user_id: str | None,
        scan_limit: int,
    ) -> list[DataMakeTemplateVersion]:
        """
        先做数据库侧预过滤，再兜底近扫描。

        过滤优先级：
        1. 显式 template_id / preferred_template_id
        2. `system_short + entity_name + executor_kind`
        3. `system_short + entity_name`
        4. `system_short`
        5. 最近版本兜底

        这样模板规模起来后，大部分查询不会再扫描全量最近版本。
        """

        preferred_template_id = self._extract_preferred_template_id(aggregate)
        filter_groups: list[dict[str, str]] = []
        if preferred_template_id:
            filter_groups.append({"template_id": preferred_template_id})
        if aggregate is not None:
            if aggregate.system_short and aggregate.entity_name and aggregate.executor_kind:
                filter_groups.append(
                    {
                        "system_short": aggregate.system_short,
                        "entity_name": aggregate.entity_name,
                        "executor_kind": aggregate.executor_kind,
                    }
                )
            if aggregate.system_short and aggregate.entity_name:
                filter_groups.append(
                    {
                        "system_short": aggregate.system_short,
                        "entity_name": aggregate.entity_name,
                    }
                )
            if aggregate.system_short:
                filter_groups.append({"system_short": aggregate.system_short})

        seen_ids: set[int] = set()
        rows: list[DataMakeTemplateVersion] = []
        for filters in filter_groups:
            query = select(DataMakeTemplateVersion).order_by(desc(DataMakeTemplateVersion.id))
            query = self._apply_row_filters(query=query, filters=filters)
            query = self._apply_governance_filters(
                query=query,
                aggregate=aggregate,
                current_user_id=current_user_id,
            )
            matched_rows = session.execute(query.limit(scan_limit)).scalars().all()
            for row in matched_rows:
                if int(row.id) in seen_ids:
                    continue
                seen_ids.add(int(row.id))
                rows.append(row)
            if len(rows) >= scan_limit:
                return rows[:scan_limit]

        if len(rows) < scan_limit:
            fallback_query = (
                select(DataMakeTemplateVersion)
                .order_by(desc(DataMakeTemplateVersion.id))
            )
            fallback_query = self._apply_governance_filters(
                query=fallback_query,
                aggregate=aggregate,
                current_user_id=current_user_id,
            )
            fallback_rows = session.execute(
                fallback_query.limit(scan_limit)
            ).scalars().all()
            for row in fallback_rows:
                if int(row.id) in seen_ids:
                    continue
                seen_ids.add(int(row.id))
                rows.append(row)
                if len(rows) >= scan_limit:
                    break
        return rows

    def _apply_row_filters(
        self,
        *,
        query: Any,
        filters: dict[str, str],
    ) -> Any:
        """
        把模板检索过滤条件应用到 SQL 查询。
        """

        for field, value in filters.items():
            if field == "template_id":
                query = query.where(DataMakeTemplateVersion.template_id == value)
            elif field == "system_short":
                query = query.where(DataMakeTemplateVersion.system_short == value)
            elif field == "entity_name":
                query = query.where(DataMakeTemplateVersion.entity_name == value)
            elif field == "executor_kind":
                query = query.where(DataMakeTemplateVersion.executor_kind == value)
        return query

    def _apply_governance_filters(
        self,
        *,
        query: Any,
        aggregate: FlowDraftAggregate | None,
        current_user_id: str | None,
    ) -> Any:
        """
        给模板检索查询补充治理侧过滤条件。

        当前阶段只做最小但关键的治理约束：
        - `private` 模板默认只对发布者本人可见
        - 支持通过 flow_draft 参数显式收缩到某个发布人 / 可见性集合 / 审批通过模板
        """

        query = query.where(self._build_visibility_clause(current_user_id))

        publisher_user_id = self._extract_query_str(
            aggregate,
            "preferred_publisher_user_id",
            "publisher_user_id",
        )
        if publisher_user_id is not None:
            query = query.where(DataMakeTemplateVersion.publisher_user_id == publisher_user_id)

        approval_only = self._extract_query_bool(
            aggregate,
            "template_only_approved",
            "approval_passed_only",
        )
        if approval_only is True:
            query = query.where(DataMakeTemplateVersion.approval_passed.is_(True))

        visibility_scope = self._extract_visibility_scope(aggregate)
        visibility_clause = self._build_requested_visibility_clause(
            visibility_scope=visibility_scope,
            current_user_id=current_user_id,
        )
        if visibility_clause is not None:
            query = query.where(visibility_clause)
        return query

    def _build_visibility_clause(self, current_user_id: str | None) -> Any:
        """
        构建“当前调用方能看到哪些模板”的基础可见性约束。
        """

        public_clause = or_(
            DataMakeTemplateVersion.visibility.is_(None),
            DataMakeTemplateVersion.visibility.in_(["shared", "global"]),
        )
        normalized_user_id = self._optional_str(current_user_id)
        if normalized_user_id is None:
            return public_clause
        return or_(
            public_clause,
            DataMakeTemplateVersion.publisher_user_id == normalized_user_id,
        )

    def _build_requested_visibility_clause(
        self,
        *,
        visibility_scope: set[str] | None,
        current_user_id: str | None,
    ) -> Any | None:
        """
        把调用方显式声明的可见性范围转成 SQL 过滤条件。
        """

        if not visibility_scope:
            return None

        clauses: list[Any] = []
        if "global" in visibility_scope:
            clauses.append(DataMakeTemplateVersion.visibility == "global")
            clauses.append(DataMakeTemplateVersion.visibility.is_(None))
        if "shared" in visibility_scope:
            clauses.append(DataMakeTemplateVersion.visibility == "shared")
        if "private" in visibility_scope and self._optional_str(current_user_id) is not None:
            clauses.append(DataMakeTemplateVersion.visibility == "private")
        if not clauses:
            return None
        return or_(*clauses)

    def _score_snapshot(
        self,
        *,
        row: DataMakeTemplateVersion,
        snapshot: TemplateVersionSnapshot,
        task: str,
        aggregate: FlowDraftAggregate | None,
        current_user_id: str | None,
        run_stats: dict[str, Any],
    ) -> TemplateCandidateDigest | None:
        """
        对单个模板版本快照做规则打分。

        当前首版不引入向量索引，改用以下稳定信号：
        - system/entity/executor 命中
        - task/goal 文本 token 重合
        - 参数命中率
        - 环境参数命中

        这样虽然还不够“智能”，但已经比只看最近版本稳定很多。
        """

        metadata = snapshot.compiled_dag.metadata if isinstance(snapshot.compiled_dag.metadata, dict) else {}
        score = 0.0
        reasons: list[str] = []
        matched_params: list[str] = []
        score_breakdown: dict[str, float] = {}

        semantic_similarity = self._compute_semantic_similarity(
            task=task,
            aggregate=aggregate,
            snapshot=snapshot,
        )
        semantic_score = round(
            semantic_similarity * self.score_weights["semantic"],
            3,
        )
        if semantic_score > 0:
            score += semantic_score
            score_breakdown["semantic"] = semantic_score
            reasons.append(f"语义相似度: {semantic_similarity:.3f}")

        if aggregate is not None:
            if aggregate.system_short and aggregate.system_short == metadata.get("system_short"):
                score += 3.0
                score_breakdown["system"] = score_breakdown.get("system", 0.0) + 3.0
                reasons.append(f"目标系统命中: {aggregate.system_short}")
            if aggregate.entity_name and aggregate.entity_name == metadata.get("entity_name"):
                score += 3.0
                score_breakdown["entity"] = score_breakdown.get("entity", 0.0) + 3.0
                reasons.append(f"目标实体命中: {aggregate.entity_name}")
            if aggregate.executor_kind and aggregate.executor_kind == metadata.get("executor_kind"):
                score += 2.0
                score_breakdown["executor"] = score_breakdown.get("executor", 0.0) + 2.0
                reasons.append(f"执行方式命中: {aggregate.executor_kind}")

            ready_params = aggregate.ready_params
            if ready_params:
                param_keys = set(snapshot.params_schema.keys())
                overlap = sorted(key for key in ready_params.keys() if key in param_keys)
                if overlap:
                    matched_params = overlap
                    coverage = len(overlap) / max(len(param_keys), 1)
                    param_score = min(coverage * 2.0, 2.0)
                    score += param_score
                    score_breakdown["params"] = param_score
                    reasons.append(
                        f"参数命中: {len(overlap)}/{len(param_keys) or len(overlap)}"
                    )
                target_env = ready_params.get("target_environment")
                snapshot_env = (
                    snapshot.params_schema.get("target_environment", {}).get("default")
                    if isinstance(snapshot.params_schema.get("target_environment"), dict)
                    else None
                )
                if (
                    isinstance(target_env, str)
                    and isinstance(snapshot_env, str)
                    and target_env == snapshot_env
                ):
                    score += 1.0
                    score_breakdown["environment"] = 1.0
                    reasons.append(f"环境命中: {target_env}")

            risk_score, risk_reason = self._score_risk_preference(
                aggregate=aggregate,
                candidate_risk=self._normalize_risk_level(
                    snapshot.metadata.get("risk_level")
                ),
            )
            if risk_score != 0:
                score += risk_score
                score_breakdown["risk"] = risk_score
                reasons.append(risk_reason)

            env_tag_score, env_tag_reason = self._score_env_tags(
                aggregate=aggregate,
                row=row,
                snapshot=snapshot,
            )
            if env_tag_score != 0:
                score += env_tag_score
                score_breakdown["env_tag"] = env_tag_score
                reasons.append(env_tag_reason)

            effect_tag_score, effect_tag_reason = self._score_effect_tags(
                task=task,
                aggregate=aggregate,
                row=row,
                snapshot=snapshot,
            )
            if effect_tag_score != 0:
                score += effect_tag_score
                score_breakdown["effect_tag"] = effect_tag_score
                reasons.append(effect_tag_reason)

        task_tokens = self._tokenize(task)
        goal_tokens = self._tokenize(snapshot.goal_summary or snapshot.template_name)
        overlap_tokens = task_tokens & goal_tokens
        if overlap_tokens:
            lexical_score = min(
                len(overlap_tokens) * self.score_weights["lexical"],
                2.0,
            )
            score += lexical_score
            score_breakdown["lexical"] = lexical_score
            reasons.append(
                "任务语义重合: " + "/".join(sorted(list(overlap_tokens))[:4])
            )

        step_count = len(snapshot.compiled_dag.steps)
        if step_count > 0:
            score += 0.2
            score_breakdown["structure"] = 0.2

        history_score, history_reason = self._score_run_history(run_stats)
        if history_score != 0:
            score += history_score
            score_breakdown["history"] = history_score
            reasons.append(history_reason)

        ownership_score, ownership_reason = self._score_ownership_and_visibility(
            row=row,
            current_user_id=current_user_id,
        )
        if ownership_score != 0:
            score += ownership_score
            score_breakdown["ownership"] = ownership_score
            reasons.append(ownership_reason)

        approval_score, approval_reason = self._score_approval_status(row)
        if approval_score != 0:
            score += approval_score
            score_breakdown["approval"] = approval_score
            reasons.append(approval_reason)

        if score <= 0:
            return None

        return TemplateCandidateDigest(
            template_version_id=snapshot.template_version_id,
            template_id=snapshot.template_id,
            version=snapshot.version,
            template_name=snapshot.template_name,
            task_id=snapshot.task_id,
            goal_summary=snapshot.goal_summary,
            step_count=step_count,
            score=round(score, 3),
            match_reasons=reasons,
            matched_params=matched_params,
            semantic_similarity=round(semantic_similarity, 4),
            execution_success_rate=run_stats.get("success_rate"),
            recent_run_count=int(run_stats.get("recent_run_count", 0)),
            last_success_run_at=run_stats.get("last_success_run_at"),
            risk_level=self._normalize_risk_level(snapshot.metadata.get("risk_level")),
            score_breakdown={key: round(value, 3) for key, value in score_breakdown.items()},
            visibility=self._normalize_visibility(row.visibility),
            publisher_user_id=self._optional_str(row.publisher_user_id),
            approval_passed=row.approval_passed if isinstance(row.approval_passed, bool) else None,
        )

    def _normalize_flow_draft(
        self,
        flow_draft: dict[str, Any] | FlowDraftAggregate | None,
    ) -> FlowDraftAggregate | None:
        """
        把调用方提供的 flow_draft 归一成聚合根视图。

        设计约束：
        - 主链应优先直接传入持久化 `FlowDraftAggregate`
        - 这里只保留 dict -> aggregate 的兼容桥，避免旧调用方立刻失效
        """

        if isinstance(flow_draft, FlowDraftAggregate):
            return flow_draft
        if not isinstance(flow_draft, dict):
            return None

        payload = dict(flow_draft)
        confirmed_params = payload.get("confirmed_params")
        if "params" not in payload and isinstance(confirmed_params, dict):
            payload["params"] = {
                str(key): {
                    "value": value,
                    "status": "ready",
                    "source": "confirmed_params",
                }
                for key, value in confirmed_params.items()
            }
        payload.setdefault("task_id", str(payload.get("task_id") or "retrieval_probe"))
        return FlowDraftAggregate.model_validate(payload)

    def _tokenize(self, text: str | None) -> set[str]:
        """
        把自然语言文本做成首版粗粒度 token 集。

        这里不追求复杂中文分词，只做工程上足够稳定的轻量切分，
        便于在没有向量索引前先提供弱语义信号。
        """

        if not isinstance(text, str) or not text.strip():
            return set()
        raw_tokens = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", text.lower())
        tokens = {token for token in raw_tokens if len(token) >= 2}
        return tokens

    def _compute_semantic_similarity(
        self,
        *,
        task: str,
        aggregate: FlowDraftAggregate | None,
        snapshot: TemplateVersionSnapshot,
    ) -> float:
        """
        计算一个本地 embedding 相似度分数。

        当前阶段不强依赖外部 embedding 模型，改用可重复、无网络依赖的哈希向量：
        - 优点是本地可跑、稳定、零外部依赖
        - 缺点是语义能力弱于真 embedding

        后续若接入正式 embedding 模型，只需替换这里，不影响上层检索边界。
        """

        query_text = self._build_query_text(task=task, aggregate=aggregate)
        candidate_text = self._build_candidate_text(snapshot)
        query_vector = self._build_embedding(query_text)
        candidate_vector = self._build_embedding(candidate_text)
        return self._cosine_similarity(query_vector, candidate_vector)

    def _build_query_text(
        self,
        *,
        task: str,
        aggregate: FlowDraftAggregate | None,
    ) -> str:
        parts = [task]
        if aggregate is not None:
            for value in (
                aggregate.goal_summary,
                aggregate.system_short,
                aggregate.entity_name,
                aggregate.executor_kind,
            ):
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            if aggregate.ready_params:
                parts.extend(str(key) for key in sorted(aggregate.ready_params.keys()))
                parts.extend(
                    str(value)
                    for value in aggregate.ready_params.values()
                    if isinstance(value, (str, int, float, bool))
                )
        return " ".join(parts)

    def _build_candidate_text(self, snapshot: TemplateVersionSnapshot) -> str:
        metadata = snapshot.compiled_dag.metadata if isinstance(snapshot.compiled_dag.metadata, dict) else {}
        parts = [
            snapshot.template_name,
            snapshot.goal_summary,
            str(metadata.get("system_short") or ""),
            str(metadata.get("entity_name") or ""),
            str(metadata.get("executor_kind") or ""),
        ]
        parts.extend(step.name for step in snapshot.compiled_dag.steps if step.name)
        parts.extend(step.kind for step in snapshot.compiled_dag.steps if step.kind)
        parts.extend(str(key) for key in sorted(snapshot.params_schema.keys()))
        return " ".join(parts)

    def _build_hashed_embedding(self, text: str, dim: int = 64) -> list[float]:
        vector = [0.0] * dim
        for token in self._tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % dim
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 8) * 0.05
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _build_embedding(self, text: str) -> list[float]:
        """
        生成检索用 embedding。

        优先级：
        1. 调用方注入的 `embedding_provider`
        2. 注入的 `BaseEmbedding`
        3. 本地 hashed embedding 兜底
        """

        vector: list[float] | None = None
        if self.embedding_provider is not None:
            try:
                candidate = self.embedding_provider(text)
                if isinstance(candidate, list) and candidate:
                    vector = [float(item) for item in candidate]
            except Exception:
                vector = None

        if vector is None and self.embedding_model is not None:
            try:
                encoded = self.embedding_model.encode(text)
                if isinstance(encoded, list) and encoded:
                    first = encoded[0]
                    if isinstance(first, list):
                        vector = [float(item) for item in first]
                    else:
                        vector = [float(item) for item in encoded]
            except Exception:
                vector = None

        if vector is None:
            return self._build_hashed_embedding(text)

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _cosine_similarity(
        self,
        left: list[float],
        right: list[float],
    ) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))

    def _score_run_history(self, run_stats: dict[str, Any]) -> tuple[float, str]:
        """
        根据模板执行历史生成排序加权。
        """

        success_rate = run_stats.get("success_rate")
        recent_run_count = int(run_stats.get("recent_run_count", 0) or 0)
        last_success_run_at = run_stats.get("last_success_run_at")
        if success_rate is None or recent_run_count <= 0:
            return 0.0, "缺少执行历史，历史分保持中性"

        score = round((float(success_rate) - 0.5) * 2.4, 3)
        if isinstance(last_success_run_at, datetime):
            if last_success_run_at.tzinfo is None:
                last_success_run_at = last_success_run_at.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - last_success_run_at).total_seconds() / 3600
            if age_hours <= 24:
                score += 0.4
            elif age_hours <= 24 * 7:
                score += 0.2
        return score, f"执行历史命中: success_rate={float(success_rate):.2f}, runs={recent_run_count}"

    def _score_risk_preference(
        self,
        *,
        aggregate: FlowDraftAggregate,
        candidate_risk: str,
    ) -> tuple[float, str]:
        """
        根据当前任务风险偏好对候选模板做加权。

        当前优先级：
        1. `params.risk_preference`
        2. `latest_risk`
        3. 无偏好时中性
        """

        preference = self._resolve_risk_preference(aggregate)
        if preference is None:
            return 0.0, "未声明风险偏好，风险分保持中性"

        diff = self._risk_rank(candidate_risk) - self._risk_rank(preference)
        if diff <= 0:
            score = 0.8 if diff == 0 else 0.4
            return score, f"风险偏好命中: 偏好={preference}, 模板={candidate_risk}"
        penalty = round(-0.8 * diff, 3)
        return penalty, f"模板风险高于偏好: 偏好={preference}, 模板={candidate_risk}"

    def _score_ownership_and_visibility(
        self,
        *,
        row: DataMakeTemplateVersion,
        current_user_id: str | None,
    ) -> tuple[float, str]:
        """
        根据模板归属和可见性做加权。

        设计意图：
        - 当前用户自己发布过的模板，通常更贴近其真实参数习惯和审批边界。
        - `shared/global` 仍可作为复用资产，但优先级应低于“自己已经跑通”的模板。
        """

        normalized_user_id = self._optional_str(current_user_id)
        publisher_user_id = self._optional_str(row.publisher_user_id)
        visibility = self._normalize_visibility(row.visibility)

        if normalized_user_id is not None and publisher_user_id == normalized_user_id:
            return self.score_weights["ownership"], "发布人命中: 当前用户自己发布"
        if visibility == "shared":
            return self.score_weights["shared_visibility"], "可见性命中: shared"
        if visibility == "global":
            return self.score_weights["global_visibility"], "可见性命中: global"
        return 0.0, "可见性分保持中性"

    def _score_approval_status(
        self,
        row: DataMakeTemplateVersion,
    ) -> tuple[float, str]:
        """
        根据模板版本冻结时的审批结果做加权。
        """

        if row.approval_required is True and row.approval_passed is True:
            return self.score_weights["approval_passed"], "审批命中: 已有明确通过记录"
        if row.approval_required is True and row.approval_passed is not True:
            return self.score_weights["approval_missing"], "审批缺失: 需要审批但未看到通过结果"
        return 0.0, "审批分保持中性"

    def _score_env_tags(
        self,
        *,
        aggregate: FlowDraftAggregate,
        row: DataMakeTemplateVersion,
        snapshot: TemplateVersionSnapshot,
    ) -> tuple[float, str]:
        """
        对环境标签做匹配加权。
        """

        query_tags = self._extract_query_env_tags(aggregate)
        if not query_tags:
            return 0.0, "未声明环境标签，环境标签分保持中性"

        candidate_tags = self._normalize_tags(
            row.env_tags_json
            if row.env_tags_json is not None
            else snapshot.metadata.get("env_tags")
        )
        overlap = sorted(query_tags & candidate_tags)
        if not overlap:
            return 0.0, "环境标签未命中"
        score = min(len(overlap) * self.score_weights["env_tag"], 1.6)
        return round(score, 3), "环境标签命中: " + "/".join(overlap[:4])

    def _score_effect_tags(
        self,
        *,
        task: str,
        aggregate: FlowDraftAggregate,
        row: DataMakeTemplateVersion,
        snapshot: TemplateVersionSnapshot,
    ) -> tuple[float, str]:
        """
        对影响标签做匹配加权。
        """

        query_tags = self._extract_query_effect_tags(task=task, aggregate=aggregate)
        if not query_tags:
            return 0.0, "未提取到影响标签，影响标签分保持中性"

        candidate_tags = self._normalize_tags(
            row.effect_tags_json
            if row.effect_tags_json is not None
            else snapshot.metadata.get("effect_tags")
        )
        overlap = sorted(query_tags & candidate_tags)
        if not overlap:
            return 0.0, "影响标签未命中"
        score = min(len(overlap) * self.score_weights["effect_tag"], 1.2)
        return round(score, 3), "影响标签命中: " + "/".join(overlap[:4])

    def _resolve_risk_preference(
        self,
        aggregate: FlowDraftAggregate,
    ) -> str | None:
        if isinstance(aggregate.params.get("risk_preference"), dict):
            value = aggregate.params["risk_preference"].get("value")
            normalized = self._normalize_optional_risk_level(value)
            if normalized:
                return normalized
        return self._normalize_optional_risk_level(aggregate.latest_risk)

    def _normalize_risk_level(self, value: Any) -> str:
        if isinstance(value, str) and value.strip():
            normalized = value.strip().lower()
            if normalized in {"low", "medium", "high", "critical"}:
                return normalized
        return "low"

    def _normalize_optional_risk_level(self, value: Any) -> str | None:
        """
        归一化“可选风险偏好”。

        与模板自身风险等级不同，当前任务若没有显式声明风险偏好，
        检索排序必须保持中性，不能偷偷回退成 `low`。
        """

        if isinstance(value, str) and value.strip():
            normalized = value.strip().lower()
            if normalized in {"low", "medium", "high", "critical"}:
                return normalized
        return None

    def _risk_rank(self, risk_level: str) -> int:
        return {
            "low": 1,
            "medium": 2,
            "high": 3,
            "critical": 4,
        }.get(risk_level, 1)

    def _extract_preferred_template_id(
        self,
        aggregate: FlowDraftAggregate | None,
    ) -> str | None:
        """
        解析当前任务显式声明的模板偏好。

        这条信号优先级最高，因为它通常来自用户明确指定，
        比系统/实体的模糊匹配更可信。
        """

        if aggregate is None:
            return None
        for key in ("preferred_template_id", "template_id"):
            item = aggregate.params.get(key)
            if isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    def _extract_visibility_scope(
        self,
        aggregate: FlowDraftAggregate | None,
    ) -> set[str] | None:
        """
        从 flow_draft 参数中提取模板可见性范围过滤条件。
        """

        raw_value = self._extract_param_value(
            aggregate,
            "template_visibility_scope",
            "template_visibility",
            "visibility",
        )
        if raw_value is None:
            return None

        values: list[str] = []
        if isinstance(raw_value, str):
            values = [item.strip().lower() for item in raw_value.split(",")]
        elif isinstance(raw_value, list):
            values = [
                str(item).strip().lower()
                for item in raw_value
                if isinstance(item, str) and item.strip()
            ]

        normalized = {item for item in values if item in {"private", "shared", "global"}}
        return normalized or None

    def _extract_query_bool(
        self,
        aggregate: FlowDraftAggregate | None,
        *keys: str,
    ) -> bool | None:
        """
        从 flow_draft 参数中提取布尔过滤条件。
        """

        raw_value = self._extract_param_value(aggregate, *keys)
        return raw_value if isinstance(raw_value, bool) else None

    def _extract_query_str(
        self,
        aggregate: FlowDraftAggregate | None,
        *keys: str,
    ) -> str | None:
        """
        从 flow_draft 参数中提取字符串过滤条件。
        """

        raw_value = self._extract_param_value(aggregate, *keys)
        return self._optional_str(raw_value)

    def _extract_param_value(
        self,
        aggregate: FlowDraftAggregate | None,
        *keys: str,
    ) -> Any:
        """
        统一从结构化参数池里读取参数值。
        """

        if aggregate is None:
            return None
        for key in keys:
            item = aggregate.params.get(key)
            if isinstance(item, dict):
                return item.get("value")
        return None

    def _extract_query_env_tags(
        self,
        aggregate: FlowDraftAggregate,
    ) -> set[str]:
        """
        从当前任务草稿提取环境标签。
        """

        tags: set[str] = set()
        for key in ("target_environment", "environment", "env"):
            value = aggregate.ready_params.get(key)
            if isinstance(value, str) and value.strip():
                tags.add(value.strip().lower())
        return tags

    def _extract_query_effect_tags(
        self,
        *,
        task: str,
        aggregate: FlowDraftAggregate,
    ) -> set[str]:
        """
        从当前任务提取粗粒度影响标签。
        """

        tags: set[str] = set()
        for value in (
            task,
            aggregate.goal_summary,
            aggregate.system_short,
            aggregate.entity_name,
            aggregate.executor_kind,
        ):
            if isinstance(value, str) and value.strip():
                tags.update(self._extract_action_tags(value))
                tags.add(value.strip().lower())
        for step in aggregate.steps:
            if isinstance(step, dict):
                for key in ("name", "executor_type", "step_key"):
                    value = step.get(key)
                    if isinstance(value, str) and value.strip():
                        tags.update(self._extract_action_tags(value))
                        tags.add(value.strip().lower())
        return tags

    def _extract_action_tags(self, text: str) -> set[str]:
        """
        从任务文本里提取粗粒度动作标签。
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

    def _normalize_tags(self, value: Any) -> set[str]:
        """
        把 JSON/list 形态的标签字段归一成集合。
        """

        if not isinstance(value, list):
            return set()
        return {
            item.strip().lower()
            for item in value
            if isinstance(item, str) and item.strip()
        }

    def _normalize_visibility(self, value: Any) -> str:
        """
        把可见性字段归一化，兼容历史空值。
        """

        normalized = self._optional_str(value)
        if normalized in {"private", "shared", "global"}:
            return str(normalized)
        return "global"

    def _optional_str(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _load_run_stats(
        self,
        *,
        session: Session,
        template_version_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        """
        批量加载模板运行历史统计。
        """

        if not template_version_ids:
            return {}

        rows = session.execute(
            select(DataMakeTemplateRun)
            .where(DataMakeTemplateRun.template_version_id.in_(template_version_ids))
            .order_by(
                DataMakeTemplateRun.template_version_id.asc(),
                DataMakeTemplateRun.id.desc(),
            )
        ).scalars().all()

        grouped: dict[int, list[DataMakeTemplateRun]] = {}
        for row in rows:
            grouped.setdefault(int(row.template_version_id), []).append(row)

        stats: dict[int, dict[str, Any]] = {}
        for template_version_id, run_rows in grouped.items():
            recent_rows = run_rows[:10]
            success_rows = [row for row in recent_rows if row.status == "success"]
            last_success = next(
                (row.created_at for row in recent_rows if row.status == "success"),
                None,
            )
            stats[template_version_id] = {
                "recent_run_count": len(recent_rows),
                "success_rate": (
                    round(len(success_rows) / len(recent_rows), 4)
                    if recent_rows
                    else None
                ),
                "last_success_run_at": last_success,
            }
        return stats

    @contextmanager
    def _new_session(self) -> Generator[Session, None, None]:
        session = self.session_factory()
        if not isinstance(session, Session):
            raise TypeError("TemplateRetrievalService 需要返回 SQLAlchemy Session 的 session_factory")
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
