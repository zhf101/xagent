"""SQL Brain 的执行前只读探测器。"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.engine import URL, make_url

from xagent.core.database.adapters import create_adapter_for_type
from xagent.core.database.config import database_connection_config_from_url

from .llm_utils import run_async_sync
from .models import SqlExecutionProbeResult, SqlExecutionProbeTarget

EXPLAIN_SUPPORTED_TYPES = {
    "postgresql",
    "kingbase",
    "gaussdb",
    "vastbase",
    "highgo",
    "mysql",
    "tidb",
    "oceanbase",
    "polardb",
    "goldendb",
    "sqlite",
    "clickhouse",
}


def _normalize_probe_sql(sql: str) -> str:
    return sql.strip().rstrip(";")


def _is_read_query(sql: str) -> bool:
    normalized = sql.lstrip().lower()
    return normalized.startswith("select ") or normalized.startswith("with ")


def _build_probe_sql(
    sql: str,
    *,
    db_type: str | None,
    mode: str,
) -> str:
    """按数据库方言构造只读探测 SQL。

    当前只支持 SELECT / CTE：
    - `dry_run`：包裹成零结果查询，尽量覆盖语法、表、列解析
    - `explain`：对支持的数据库直接做 EXPLAIN
    """

    base_sql = _normalize_probe_sql(sql)
    if not _is_read_query(base_sql):
        raise ValueError("execution probe only supports read-only SELECT/CTE queries")

    normalized_mode = str(mode or "dry_run").strip().lower()
    if normalized_mode == "explain":
        if db_type and db_type.lower() not in EXPLAIN_SUPPORTED_TYPES:
            raise ValueError(f"execution probe explain mode is not supported for {db_type}")
        return f"EXPLAIN {base_sql}"
    if normalized_mode != "dry_run":
        raise ValueError(f"unsupported execution probe mode: {mode}")

    return f"SELECT * FROM ({base_sql}) AS sql_brain_probe WHERE 1 = 0"


class SqlExecutionProbe:
    """执行前连接级探测器。

    设计目标：
    - 严格只读，不承接真实执行
    - 复用项目已有 database adapter，避免出现第二套 SQL 执行栈
    - 返回结构化结果，便于 service 把错误继续喂给 repair
    """

    def __init__(
        self,
        *,
        adapter_factory: Callable = create_adapter_for_type,
    ):
        self._adapter_factory = adapter_factory

    def probe_sql(
        self,
        *,
        sql: str,
        target: SqlExecutionProbeTarget,
        mode: str = "dry_run",
    ) -> SqlExecutionProbeResult:
        """对给定 SQL 做只读探测。"""

        adapter = None
        probe_sql = None
        try:
            url: URL = make_url(target.db_url)
            config = database_connection_config_from_url(url, read_only=True)
            resolved_db_type = target.db_type or config.db_type
            probe_sql = _build_probe_sql(
                sql,
                db_type=resolved_db_type,
                mode=mode,
            )
            adapter = self._adapter_factory(resolved_db_type, config)
            run_async_sync(adapter.execute_query(probe_sql))
            return SqlExecutionProbeResult(
                ok=True,
                execution_mode=mode,
                message="Execution probe succeeded.",
                probe_sql=probe_sql,
            )
        except Exception as exc:
            return SqlExecutionProbeResult(
                ok=False,
                execution_mode=mode,
                message="Execution probe failed.",
                error=str(exc),
                probe_sql=probe_sql,
            )
        finally:
            if adapter is not None:
                try:
                    run_async_sync(adapter.disconnect())
                except Exception:
                    pass
