"""SQL Brain 端到端服务。"""

from __future__ import annotations

from typing import Any, Iterable

from xagent.core.model.chat.basic.base import BaseLLM
from xagent.web.services.model_service import get_compact_model, get_default_model

from ..interceptors import check_sql_needs_approval
from .execution_probe import SqlExecutionProbe
from .generator import SqlBrainGenerator
from .lancedb_store import LanceDBSqlBrainStore
from .memory_store import InMemorySqlBrainStore
from .models import (
    RetrievedDDL,
    RetrievedDocumentation,
    RetrievedQuestionSql,
    SqlExecutionProbeTarget,
)
from .prompt_builder import build_sql_prompt
from .repair import repair_sql
from .retrieval import SqlBrainRetrievalService
from .store_base import SqlBrainStore
from .verifier import verify_sql


class SQLBrainService:
    """组织 retrieval、prompt、generation、verification、repair 的服务层。"""

    def __init__(
        self,
        store: SqlBrainStore | None = None,
        *,
        llm: BaseLLM | None = None,
        user_id: int | None = None,
        embedding_model: Any | None = None,
        db_dir: str | None = None,
        execution_probe: SqlExecutionProbe | None = None,
        execution_probe_target: SqlExecutionProbeTarget | None = None,
        execution_probe_mode: str = "dry_run",
    ):
        self._llm = llm or self._resolve_llm(user_id=user_id)
        self._store = store or self._build_default_store(
            embedding_model=embedding_model,
            db_dir=db_dir,
        )
        self._execution_probe = execution_probe
        self._execution_probe_target = execution_probe_target
        self._execution_probe_mode = execution_probe_mode
        self._retrieval = SqlBrainRetrievalService(self._store)
        self._generator = SqlBrainGenerator(self._llm)

    def _resolve_llm(self, *, user_id: int | None) -> BaseLLM | None:
        """优先取 compact 模型，拿不到再回退 general。"""

        if user_id is None:
            return None
        llm = get_compact_model(user_id)
        if llm is not None:
            return llm
        return get_default_model(user_id)

    def _build_default_store(
        self,
        *,
        embedding_model: Any | None,
        db_dir: str | None,
    ) -> SqlBrainStore:
        """按能力自动选择 store。

        重要设计：
        - 不再注入 CRM 的硬编码默认知识，避免错误领域偏置
        - 能用向量库就用向量库
        - 否则退回空的内存 store
        """

        if embedding_model is not None and db_dir:
            return LanceDBSqlBrainStore(db_dir=db_dir, embedding_model=embedding_model)
        return InMemorySqlBrainStore()

    def train_question_sql(
        self,
        *,
        question: str,
        sql: str,
        system_short: str | None = None,
        db_type: str | None = None,
    ) -> None:
        self._store.add_question_sql(
            RetrievedQuestionSql(
                question=question,
                sql=sql,
                system_short=system_short,
                db_type=db_type,
            )
        )

    def train_ddl(
        self,
        *,
        table_name: str,
        ddl: str,
        system_short: str | None = None,
        db_type: str | None = None,
    ) -> None:
        self._store.add_ddl(
            RetrievedDDL(
                table_name=table_name,
                ddl=ddl,
                system_short=system_short,
                db_type=db_type,
            )
        )

    def train_documentation(
        self,
        *,
        content: str,
        system_short: str | None = None,
        db_type: str | None = None,
    ) -> None:
        self._store.add_documentation(
            RetrievedDocumentation(
                content=content,
                system_short=system_short,
                db_type=db_type,
            )
        )

    def train_sql_asset(
        self,
        *,
        asset_name: str,
        sql: str | None,
        description: str | None = None,
        tags: list[str] | None = None,
        table_names: list[str] | None = None,
        sql_kind: str | None = None,
        system_short: str | None = None,
        db_type: str | None = None,
    ) -> dict[str, int]:
        """把单条已治理 SQL 资产导入 SQL Brain 训练集。

        设计目标：
        - 只吸收相对稳定、质量较高的治理资产
        - `name / description` 进入 question_sql few-shot
        - `tags / table_names / sql_kind / description` 进入 documentation 检索
        """

        trained_question_sql = 0
        trained_documentation = 0
        normalized_sql = str(sql or "").strip()
        normalized_name = str(asset_name or "").strip()
        normalized_description = str(description or "").strip()
        normalized_tags = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        normalized_tables = [
            str(table).strip() for table in (table_names or []) if str(table).strip()
        ]
        normalized_kind = str(sql_kind or "").strip().lower() or None

        if normalized_sql and normalized_name:
            self.train_question_sql(
                question=normalized_name,
                sql=normalized_sql,
                system_short=system_short,
                db_type=db_type,
            )
            trained_question_sql += 1

        if (
            normalized_sql
            and normalized_description
            and normalized_description != normalized_name
        ):
            self.train_question_sql(
                question=normalized_description,
                sql=normalized_sql,
                system_short=system_short,
                db_type=db_type,
            )
            trained_question_sql += 1

        documentation_lines = [f"SQL资产：{normalized_name}"] if normalized_name else []
        if normalized_description:
            documentation_lines.append(f"描述：{normalized_description}")
        if normalized_kind:
            documentation_lines.append(f"SQL类型：{normalized_kind}")
        if normalized_tables:
            documentation_lines.append(f"涉及表：{', '.join(normalized_tables)}")
        if normalized_tags:
            documentation_lines.append(f"标签：{', '.join(normalized_tags)}")

        if documentation_lines:
            self.train_documentation(
                content="\n".join(documentation_lines),
                system_short=system_short,
                db_type=db_type,
            )
            trained_documentation += 1

        return {
            "question_sql": trained_question_sql,
            "documentation": trained_documentation,
        }

    def train_sql_assets(
        self,
        assets: Iterable[Any],
        *,
        default_system_short: str | None = None,
        default_db_type: str | None = None,
        db_type_resolver: Any | None = None,
    ) -> dict[str, int]:
        """批量导入治理 SQL 资产。

        目前是保守策略：
        - 只读取活跃治理资产已有的结构化字段
        - 不自动从执行日志回灌，避免把脏数据直接喂进训练集
        """

        summary = {"assets": 0, "question_sql": 0, "documentation": 0}

        for asset in assets:
            config = getattr(asset, "config", None) or {}
            asset_name = str(getattr(asset, "name", "") or "").strip()
            sql_template = str(config.get("sql_template") or "").strip() or None
            description = getattr(asset, "description", None)
            system_short = getattr(asset, "system_short", None) or default_system_short
            resolved_db_type = (
                db_type_resolver(asset)
                if callable(db_type_resolver)
                else default_db_type
            )

            trained = self.train_sql_asset(
                asset_name=asset_name,
                sql=sql_template,
                description=description,
                tags=config.get("tags") or [],
                table_names=config.get("table_names") or [],
                sql_kind=config.get("sql_kind"),
                system_short=system_short,
                db_type=resolved_db_type,
            )
            summary["assets"] += 1
            summary["question_sql"] += trained["question_sql"]
            summary["documentation"] += trained["documentation"]

        return summary

    def accept_question_sql_feedback(
        self,
        *,
        question: str,
        sql: str,
        system_short: str | None = None,
        db_type: str | None = None,
        allow_high_risk: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        """把“已确认接受”的 SQL 显式回灌为 question_sql 训练样本。

        这是受控入口，不等同于自动学习：
        - 必须由调用方显式触发
        - 默认不接受高风险 SQL
        - 只有在显式允许时才会回灌高风险样本
        """

        normalized_question = str(question or "").strip()
        normalized_sql = str(sql or "").strip()
        normalized_note = str(note or "").strip()

        if not normalized_question:
            raise ValueError("question is required")
        if not normalized_sql:
            raise ValueError("accepted_sql is required")

        requires_approval, approval_reason = check_sql_needs_approval(normalized_sql)
        if requires_approval and not allow_high_risk:
            raise ValueError(
                f"accepted_sql requires explicit high-risk override: {approval_reason}"
            )

        self.train_question_sql(
            question=normalized_question,
            sql=normalized_sql,
            system_short=system_short,
            db_type=db_type,
        )

        trained_documentation = 0
        if normalized_note:
            self.train_documentation(
                content=(
                    f"用户确认 SQL 口径\n"
                    f"问题：{normalized_question}\n"
                    f"备注：{normalized_note}"
                ),
                system_short=system_short,
                db_type=db_type,
            )
            trained_documentation = 1

        return {
            "trained": True,
            "question_sql": 1,
            "documentation": trained_documentation,
            "requires_approval": requires_approval,
            "approval_reason": approval_reason,
            "system_short": system_short,
            "db_type": db_type,
        }

    def generate_sql_plan(
        self,
        question: str,
        *,
        system_short: str | None = None,
        db_type: str | None = None,
        read_only: bool = True,
        top_k: int = 5,
        execution_probe_target: SqlExecutionProbeTarget | None = None,
        execution_probe_mode: str | None = None,
    ) -> dict:
        context = self._retrieval.retrieve(
            question,
            system_short=system_short,
            db_type=db_type,
            top_k=top_k,
        )
        prompt = build_sql_prompt(context)
        generation = self._generator.generate(context)
        effective_probe_target = execution_probe_target or self._execution_probe_target
        effective_probe_mode = execution_probe_mode or self._execution_probe_mode

        verification = None
        execution_probe_result = None
        repaired = None
        if generation.sql:
            verification = verify_sql(
                generation.sql,
                db_type=db_type,
                read_only=read_only,
                ddl_snippets=context.ddl_snippets,
            )
            if (
                verification.valid
                and self._execution_probe is not None
                and effective_probe_target is not None
            ):
                execution_probe_result = self._execution_probe.probe_sql(
                    sql=generation.sql,
                    target=effective_probe_target,
                    mode=effective_probe_mode,
                )
            if not verification.valid:
                repaired = repair_sql(
                    sql=generation.sql,
                    error="; ".join(verification.reasons),
                    db_type=db_type,
                    ddl_snippets=context.ddl_snippets,
                    llm=self._llm,
                    context=context,
                )
            elif execution_probe_result is not None and not execution_probe_result.ok:
                repaired = repair_sql(
                    sql=generation.sql,
                    error=execution_probe_result.error or execution_probe_result.message,
                    db_type=db_type,
                    ddl_snippets=context.ddl_snippets,
                    llm=self._llm,
                    context=context,
                )

        return {
            "success": True,
            "prompt": prompt,
            "sql": generation.sql,
            "intermediate_sql": generation.intermediate_sql,
            "reasoning": generation.reasoning,
            "verification": verification,
            "execution_probe": execution_probe_result,
            "repair": repaired,
            "metadata": {
                "sql_brain_used": True,
                "system_short": system_short,
                "db_type": db_type,
                "read_only": read_only,
                "retrieval_mode": self._store.retrieval_mode,
                "embedding_used": self._store.embedding_enabled,
                "llm_model": self._generator.llm_model_name,
                "execution_probe_enabled": effective_probe_target is not None,
                "execution_probe_mode": effective_probe_mode
                if effective_probe_target is not None
                else None,
                "execution_probe_source": effective_probe_target.source
                if effective_probe_target is not None
                else None,
                "knowledge_counts": {
                    "question_sql": len(context.question_sql_examples),
                    "ddl": len(context.ddl_snippets),
                    "documentation": len(context.documentation_chunks),
                },
            },
        }
