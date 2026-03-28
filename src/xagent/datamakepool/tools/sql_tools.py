"""Datamakepool 的 SQL 工具集。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.tools.adapters.vibe.base import ToolCategory, ToolVisibility
from xagent.core.tools.adapters.vibe.function import FunctionTool
from xagent.datamakepool.assets.repositories import SqlAssetRepository
from xagent.datamakepool.assets.service import SqlAssetResolverService
from xagent.datamakepool.interceptors import check_sql_needs_approval
from xagent.datamakepool.recall_funnel import load_default_embedding_adapter
from xagent.datamakepool.sql_brain import SQLBrainService
from xagent.datamakepool.sql_brain.execution_probe import SqlExecutionProbe
from xagent.datamakepool.sql_brain.models import SqlExecutionProbeTarget
from xagent.datamakepool.sql_brain.schema_bootstrap import (
    load_schema_training_snippets,
)
from xagent.providers.vector_store.lancedb import LanceDBConnectionManager
from xagent.web.models.text2sql import Text2SQLDatabase
from xagent.web.models.datamakepool_asset import DataMakepoolAsset


class DatamakepoolSqlTool(FunctionTool):
    category = ToolCategory.DATABASE


def _build_default_sql_brain(
    *,
    db: Session | None,
    system_short: str | None,
    db_type: str | None,
    user_id: int | None,
    llm: BaseLLM | None,
) -> SQLBrainService:
    """按当前上下文构造默认 SQL Brain。

    这里优先复用项目现有的模型体系：
    - LLM：优先使用调用方显式传入的模型
    - embedding：有 db + user_id 时尝试读取用户默认 embedding
    """

    embedding_model = None
    if db is not None and user_id is not None:
        embedding_model = load_default_embedding_adapter(db, user_id)

    execution_probe_target = _resolve_probe_target(
        db=db,
        user_id=user_id,
        system_short=system_short,
        db_type=db_type,
    )

    return SQLBrainService(
        llm=llm,
        user_id=user_id,
        embedding_model=embedding_model,
        db_dir=LanceDBConnectionManager.get_default_lancedb_dir(),
        execution_probe=SqlExecutionProbe() if execution_probe_target else None,
        execution_probe_target=execution_probe_target,
    )


def _resolve_sql_asset_db_type(
    repository: SqlAssetRepository,
    asset: DataMakepoolAsset,
    fallback_db_type: str | None,
) -> str | None:
    """优先从 datasource 资产推断 SQL 资产的数据库类型。"""

    datasource_asset_id = getattr(asset, "datasource_asset_id", None)
    if datasource_asset_id:
        datasource_asset = repository.get_datasource_asset(int(datasource_asset_id))
        if datasource_asset is not None:
            config = datasource_asset.config or {}
            datasource_db_type = str(config.get("db_type") or "").strip().lower()
            if datasource_db_type:
                return datasource_db_type

    normalized_fallback = str(fallback_db_type or "").strip().lower()
    return normalized_fallback or None


def _bootstrap_sql_brain_from_sql_assets(
    *,
    sql_brain: SQLBrainService,
    db: Session | None,
    system_short: str | None,
    db_type: str | None,
) -> dict[str, int] | None:
    """把当前业务系统下的治理 SQL 资产导入 SQL Brain。"""

    if db is None or not system_short:
        return None

    repository = SqlAssetRepository(db)
    assets = repository.list_active_sql_assets(system_short=system_short)
    if not assets:
        return {
            "assets": 0,
            "question_sql": 0,
            "documentation": 0,
            "ddl": 0,
            "schema_sources": 0,
        }

    summary = sql_brain.train_sql_assets(
        assets,
        default_system_short=system_short,
        default_db_type=db_type,
        db_type_resolver=lambda asset: _resolve_sql_asset_db_type(
            repository,
            asset,
            db_type,
        ),
    )
    summary["ddl"] = 0
    summary["schema_sources"] = 0

    bootstrapped_datasource_ids: set[int] = set()
    for asset in assets:
        datasource_asset_id = getattr(asset, "datasource_asset_id", None)
        if not datasource_asset_id:
            continue
        normalized_datasource_id = int(datasource_asset_id)
        if normalized_datasource_id in bootstrapped_datasource_ids:
            continue
        bootstrapped_datasource_ids.add(normalized_datasource_id)

        datasource_asset = repository.get_datasource_asset(normalized_datasource_id)
        if datasource_asset is None:
            continue
        datasource_config = datasource_asset.config or {}
        datasource_url = str(datasource_config.get("url") or "").strip()
        if not datasource_url:
            continue

        datasource_db_type = _resolve_sql_asset_db_type(repository, asset, db_type)
        ddl_snippets = load_schema_training_snippets(
            db_url=datasource_url,
            db_type=datasource_db_type,
            system_short=system_short or getattr(asset, "system_short", None),
        )
        if not ddl_snippets:
            continue

        summary["schema_sources"] += 1
        summary["ddl"] += len(ddl_snippets)
        for snippet in ddl_snippets:
            sql_brain.train_ddl(
                table_name=snippet.table_name,
                ddl=snippet.ddl,
                system_short=snippet.system_short,
                db_type=snippet.db_type,
            )

    return summary


def _resolve_probe_target(
    *,
    db: Session | None,
    user_id: int | None,
    system_short: str | None,
    db_type: str | None,
    datasource_asset_id: int | None = None,
) -> SqlExecutionProbeTarget | None:
    """尝试从 Text2SQL 数据源解析 SQL Brain 的只读探测目标。

    取舍：
    - 只在当前用户、当前系统下选启用中的数据源
    - 默认选择最近创建的一条，避免在无明确绑定规则前做复杂仲裁
    - 未命中时静默降级，不阻塞 SQL 规划主链路
    """

    explicit_target = _resolve_probe_target_from_datasource_asset(
        db=db,
        datasource_asset_id=datasource_asset_id,
        db_type=db_type,
    )
    if explicit_target is not None:
        return explicit_target

    if db is None or user_id is None or not system_short:
        return None

    candidates = (
        db.query(Text2SQLDatabase)
        .filter(
            Text2SQLDatabase.user_id == user_id,
            Text2SQLDatabase.enabled.is_(True),
        )
        .order_by(Text2SQLDatabase.created_at.desc())
        .all()
    )

    normalized_system = str(system_short or "").strip().lower()
    normalized_db_type = str(db_type or "").strip().lower()

    for candidate in candidates:
        candidate_system = str(
            getattr(getattr(candidate, "system", None), "system_short", "") or ""
        ).strip().lower()
        if candidate_system != normalized_system:
            continue

        candidate_db_type = str(getattr(candidate.type, "value", "") or "").strip().lower()
        if normalized_db_type and candidate_db_type and candidate_db_type != normalized_db_type:
            continue

        return SqlExecutionProbeTarget(
            db_url=str(candidate.url),
            db_type=candidate_db_type or db_type,
            read_only=True,
            source=f"text2sql_database:{int(candidate.id)}",
        )

    return None


def _resolve_probe_target_from_datasource_asset(
    *,
    db: Session | None,
    datasource_asset_id: int | None,
    db_type: str | None,
) -> SqlExecutionProbeTarget | None:
    """按 datasource 资产显式解析 probe target。

    显式 datasource 优先级高于“按 system_short 猜最近连接”：
    - 资产页创建的 SQL 资产本身就绑定了 datasource
    - 运行期如果知道 datasource_asset_id，应该直接复用这条宿主连接
    """

    if db is None or datasource_asset_id is None:
        return None

    datasource_asset: DataMakepoolAsset | None = SqlAssetRepository(db).get_datasource_asset(
        datasource_asset_id
    )
    if datasource_asset is None:
        return None

    config = datasource_asset.config or {}
    db_url = str(config.get("url") or "").strip()
    if not db_url:
        return None

    config_db_type = str(config.get("db_type") or "").strip().lower()
    resolved_db_type = config_db_type or str(db_type or "").strip().lower() or None
    return SqlExecutionProbeTarget(
        db_url=db_url,
        db_type=resolved_db_type,
        read_only=bool(config.get("read_only", True)),
        source=f"datasource_asset:{int(datasource_asset.id)}",
    )


def create_sql_tools(
    sql_brain: SQLBrainService | None = None,
    db: Session | None = None,
    system_short: str | None = None,
    db_type: str | None = None,
    default_datasource_asset_id: int | None = None,
    user_id: int | None = None,
    llm: BaseLLM | None = None,
) -> list[FunctionTool]:
    created_default_sql_brain = sql_brain is None
    sql_brain = sql_brain or _build_default_sql_brain(
        db=db,
        system_short=system_short,
        db_type=db_type,
        user_id=user_id,
        llm=llm,
    )
    asset_bootstrap_summary = (
        _bootstrap_sql_brain_from_sql_assets(
            sql_brain=sql_brain,
            db=db,
            system_short=system_short,
            db_type=db_type,
        )
        if created_default_sql_brain
        else None
    )
    sql_asset_resolver = (
        SqlAssetResolverService(SqlAssetRepository(db))
        if db is not None
        else None
    )

    def sql_asset_check(task: str) -> dict:
        """检查任务是否可命中已治理 SQL 资产。"""

        if sql_asset_resolver is None:
            return {
                "success": False,
                "matched": False,
                "message": "No database session available for SQL asset lookup.",
            }
        result = sql_asset_resolver.resolve(
            task=task,
            system_short=system_short,
        )
        if result.matched:
            return {
                "success": True,
                "matched": True,
                "asset_id": result.asset_id,
                "asset_name": result.asset_name,
                "datasource_asset_id": result.datasource_asset_id,
                "config": result.config,
                "reason": result.reason,
            }
        return {
            "success": True,
            "matched": False,
            "reason": result.reason,
            "top_candidates": result.top_candidates or [],
            "candidate_count": result.candidate_count,
        }

    def execute_sql_plan(
        task: str,
        datasource_asset_id: int | None = None,
        force_sql_brain: bool = False,
    ) -> dict:
        """通过 SQL Brain 生成 SQL 执行方案。

        该工具只生成 plan，不直接执行 SQL。
        """

        asset_match = None
        if sql_asset_resolver is not None:
            asset_match = sql_asset_resolver.resolve(
                task=task,
                system_short=system_short,
            )

        runtime_datasource_asset_id = (
            datasource_asset_id
            or default_datasource_asset_id
            or (asset_match.datasource_asset_id if asset_match and asset_match.matched else None)
        )

        asset_sql = None
        if asset_match and getattr(asset_match, "matched", False):
            asset_config = getattr(asset_match, "config", {}) or {}
            asset_sql = str(asset_config.get("sql_template") or "").strip() or None

        if asset_sql and not force_sql_brain:
            approval_required, approval_reason = check_sql_needs_approval(asset_sql)
            return {
                "success": True,
                "executed": False,
                "plan_source": "sql_asset",
                "output": f"Matched governed SQL asset: {getattr(asset_match, 'asset_name', 'unknown')}",
                "sql": asset_sql,
                "intermediate_sql": None,
                "reasoning": f"优先复用已治理 SQL 资产 `{getattr(asset_match, 'asset_name', 'unknown')}`，未调用 SQL Brain 动态生成。",
                "verification": None,
                "execution_probe": None,
                "repair": None,
                "metadata": {
                    "sql_brain_used": False,
                    "system_short": system_short,
                    "db_type": db_type,
                    "read_only": True,
                    "plan_source": "sql_asset",
                    "asset_id": getattr(asset_match, "asset_id", None),
                    "asset_name": getattr(asset_match, "asset_name", None),
                    "datasource_asset_id": runtime_datasource_asset_id,
                    "asset_bootstrap": asset_bootstrap_summary,
                },
                "asset_match": {
                    "matched": True,
                    "asset_id": getattr(asset_match, "asset_id", None),
                    "asset_name": getattr(asset_match, "asset_name", None),
                    "datasource_asset_id": getattr(asset_match, "datasource_asset_id", None),
                    "reason": getattr(asset_match, "reason", None),
                    "score": getattr(asset_match, "score", 0.0),
                },
                "requires_approval": approval_required,
                "approval_reason": approval_reason,
            }

        probe_target = _resolve_probe_target(
            db=db,
            user_id=user_id,
            system_short=system_short,
            db_type=db_type,
            datasource_asset_id=runtime_datasource_asset_id,
        )
        generate_kwargs = {
            "system_short": system_short,
            "db_type": db_type,
        }
        if probe_target is not None:
            generate_kwargs["execution_probe_target"] = probe_target

        result = sql_brain.generate_sql_plan(
            task,
            **generate_kwargs,
        )
        sql = result.get("sql")
        intermediate_sql = result.get("intermediate_sql")
        output = (
            f"SQL Brain generated SQL: {sql}"
            if sql
            else f"SQL Brain requested intermediate SQL: {intermediate_sql}"
        )
        approval_required, approval_reason = check_sql_needs_approval(
            sql or intermediate_sql or ""
        )
        plan = {
            "success": True,
            "executed": False,
            "plan_source": "sql_brain",
            "output": output,
            "sql": sql,
            "intermediate_sql": intermediate_sql,
            "reasoning": result.get("reasoning"),
            "verification": result.get("verification"),
            "execution_probe": result.get("execution_probe"),
            "repair": result.get("repair"),
            "metadata": result.get("metadata"),
            "asset_match": (
                {
                    "matched": getattr(asset_match, "matched", False),
                    "asset_id": getattr(asset_match, "asset_id", None),
                    "asset_name": getattr(asset_match, "asset_name", None),
                    "datasource_asset_id": getattr(asset_match, "datasource_asset_id", None),
                    "reason": getattr(asset_match, "reason", None),
                    "score": getattr(asset_match, "score", 0.0),
                }
                if asset_match is not None
                else None
            ),
            "requires_approval": approval_required,
            "approval_reason": approval_reason,
        }
        if isinstance(plan.get("metadata"), dict):
            plan["metadata"]["asset_bootstrap"] = asset_bootstrap_summary
        return plan

    return [
        DatamakepoolSqlTool(
            sql_asset_check,
            name="sql_asset_check",
            description="Check approved SQL assets before generating temporary SQL.",
            visibility=ToolVisibility.PRIVATE,
        ),
        DatamakepoolSqlTool(
            execute_sql_plan,
            name="execute_sql_plan",
            description="Generate a SQL execution plan (plan only, not executed). Returns generated SQL for review before execution.",
            visibility=ToolVisibility.PRIVATE,
        ),
    ]
