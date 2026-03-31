"""
SQL Tool for xagent - SQL execution using SQLAlchemy

Database connections are configured via environment variables, not raw URLs.
Connection format: XAGENT_EXTERNAL_DB_<NAME>=<connection_url>

Example:
    XAGENT_EXTERNAL_DB_ANALYTICS=postgresql://user:pass@localhost:5432/analytics
    XAGENT_EXTERNAL_DB_PROD=mysql+pymysql://user:pass@localhost:3306/production
    XAGENT_EXTERNAL_DB_LOCAL=sqlite:///path/to/database.db
    XAGENT_EXTERNAL_DB_DUCKDB=duckdb:///path/to/database.duckdb

Note: This tool uses SQLAlchemy's synchronous engine.
Async drivers are not supported currently.
"""

import csv
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import CursorResult, Row, make_url

from ...database.adapters import create_adapter_for_type
from ...database.adapters.sqlalchemy_common import SqlAlchemySyncAdapter
from ...database.config import database_connection_config_from_url

if TYPE_CHECKING:
    from ...workspace import TaskWorkspace

logger = logging.getLogger(__name__)


class SQLQueryArgs(BaseModel):
    """Arguments for SQL query execution."""

    connection_name: str = Field(description="Database connection name to use")
    query: str = Field(description="SQL query to execute")


class SQLQueryResult(BaseModel):
    """Result from SQL query execution in LLM-friendly format"""

    success: bool = Field(description="Whether the query executed successfully")
    rows: list[dict[str, Any]] = Field(
        default_factory=list, description="Query result rows as list of dictionaries"
    )
    row_count: int = Field(default=0, description="Number of rows affected/returned")
    columns: list[str] = Field(
        default_factory=list, description="Column names in result set"
    )
    message: str = Field(default="", description="Summary of what happened")


def _get_connection_url(connection_name: str) -> URL:
    """Get database connection URL from environment variable.

    Environment variable format: XAGENT_EXTERNAL_DB_<NAME>=<connection_url>

    Args:
        connection_name: Name of the connection (case-insensitive)

    Returns:
        Connection URL if found
    """
    env_key = f"XAGENT_EXTERNAL_DB_{connection_name.upper()}"
    url = os.getenv(env_key)

    if not url:
        raise ValueError(f"Database connection '{connection_name}' not found.")

    # Validate URL format using SQLAlchemy
    return make_url(url)


def get_database_type(connection_name: str) -> str:
    """Get database type for a connection name.

    Returns the database driver/type which helps LLM write appropriate SQL dialect.
    Examples: postgresql, mysql, sqlite, duckdb

    Args:
        connection_name: Name of the connection (case-insensitive)

    Returns:
        Database type (driver name)
    """
    url = _get_connection_url(connection_name)
    return database_connection_config_from_url(url, read_only=True).db_type


def _row_to_dict(row: Row) -> dict[str, Any]:
    """Convert SQLAlchemy Row to dictionary"""
    return dict(row._mapping)


def execute_sql_query(
    connection_name: str,
    query: str,
    output_file: Optional[str] = None,
    workspace: Optional["TaskWorkspace"] = None,
) -> dict[str, Any]:
    """Execute SQL queries on databases and return structured results.

    Args:
        connection_name: Database connection name to use
        query: SQL statement to execute
        output_file: Optional file path to export query results.
            Supported formats: .csv, .parquet, .json, .jsonl, .ndjson (relative to workspace output directory).
            When provided, query results are exported to file instead of being returned.
        workspace: Optional TaskWorkspace instance for file exports.

    Returns:
        dict:
            with keys:
            - success: true if query worked
            - rows: query results as list of dicts (SELECT only, empty when exported)
            - row_count: number of rows returned or affected
            - columns: column names in the result
            - message: what happened
    """
    url = _get_connection_url(connection_name)
    config = database_connection_config_from_url(url, read_only=False)
    adapter = _create_adapter_if_supported(config)

    # 对导出场景优先保留历史 SQLAlchemy 流式写盘能力，避免把整表结果先堆进内存。
    if output_file and workspace:
        streaming_url = _resolve_streaming_sqlalchemy_url(url=url, adapter=adapter)
        if streaming_url is not None:
            return _execute_sqlalchemy_query_sync(
                connection_name=connection_name,
                url=streaming_url,
                query=query,
                output_file=output_file,
                workspace=workspace,
            )

    # 对尚未纳入 adapter 白名单、但历史上可被 SQLAlchemy 直接执行的方言，
    # 继续走兼容路径，例如 `duckdb:///...`。
    if adapter is None:
        return _execute_sqlalchemy_query_sync(
            connection_name=connection_name,
            url=url,
            query=query,
            output_file=output_file,
            workspace=workspace,
        )

    import asyncio

    async def _run_query() -> dict[str, Any]:
        await adapter.connect()
        try:
            result = await adapter.execute_query(query)
        finally:
            await adapter.disconnect()

        columns = list(result.rows[0].keys()) if result.rows else []
        if output_file and workspace:
            exported_count = _export_rows_to_file(
                workspace=workspace,
                output_file=output_file,
                rows=result.rows,
                columns=columns,
            )
            return SQLQueryResult(
                success=True,
                rows=[],
                row_count=exported_count,
                columns=columns,
                message=f"Query executed successfully on '{connection_name}', exported {exported_count} row(s) to {output_file}",
            ).model_dump()

        row_count = len(result.rows) if result.rows else int(result.affected_rows or 0)
        return SQLQueryResult(
            success=True,
            rows=result.rows,
            row_count=row_count,
            columns=columns,
            message=(
                f"Query executed successfully on '{connection_name}', returned {len(result.rows)} row(s)"
                if result.rows
                else f"Query executed successfully on '{connection_name}', affected {row_count} row(s)"
            ),
        ).model_dump()

    return _run_coroutine_safely(_run_query())


def _create_adapter_if_supported(config: Any) -> Any | None:
    """按数据库类型尝试创建 adapter；不支持时回退到历史 SQLAlchemy 路径。"""

    try:
        return create_adapter_for_type(config.db_type, config)
    except ValueError:
        return None


def _resolve_streaming_sqlalchemy_url(*, url: URL, adapter: Any | None) -> URL | None:
    """为导出场景解析可流式执行的 SQLAlchemy URL。

    优先级：
    1. SQLAlchemy 家族 adapter 的最终 driver URL
    2. 历史直接透传的原始 URL
    3. 非 SQLAlchemy adapter（如 ClickHouse / DM）返回 `None`
    """

    if isinstance(adapter, SqlAlchemySyncAdapter):
        try:
            return adapter.build_sqlalchemy_url()
        except Exception:
            return None
    if adapter is None:
        return url
    return None


def _looks_like_write_operation(query: str) -> bool:
    """按首个关键字粗粒度判断是否属于写操作。"""

    tokens = query.strip().lower().split(None, 1)
    return bool(tokens) and tokens[0] in {
        "insert",
        "update",
        "delete",
        "alter",
        "drop",
        "truncate",
        "create",
        "replace",
        "merge",
    }


def _execute_sqlalchemy_query_sync(
    *,
    connection_name: str,
    url: URL,
    query: str,
    output_file: Optional[str] = None,
    workspace: Optional["TaskWorkspace"] = None,
) -> dict[str, Any]:
    """保留历史 SQLAlchemy 兼容路径。

    这条路径现在承担两个职责：
    - 继续兼容 adapter 白名单之外、但 SQLAlchemy 已支持的历史方言
    - 在导出场景继续复用 `CursorResult` 流式写盘，避免整表 materialize
    """

    stmt = text(query)
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            if output_file and workspace:
                result = conn.execute(stmt)
                exported_count, columns = _stream_result_to_file(
                    workspace=workspace,
                    output_file=output_file,
                    result=result,
                )
                return SQLQueryResult(
                    success=True,
                    rows=[],
                    row_count=exported_count,
                    columns=columns,
                    message=f"Query executed successfully on '{connection_name}', exported {exported_count} row(s) to {output_file}",
                ).model_dump()

            result = conn.execute(stmt)
            if result.returns_rows:
                rows = [dict(row._mapping) for row in result.fetchall()]
                columns = list(rows[0].keys()) if rows else list(result.keys())
                return SQLQueryResult(
                    success=True,
                    rows=rows,
                    row_count=len(rows),
                    columns=columns,
                    message=f"Query executed successfully on '{connection_name}', returned {len(rows)} row(s)",
                ).model_dump()

            row_count = result.rowcount if hasattr(result, "rowcount") else 0
            if _looks_like_write_operation(query):
                conn.commit()
            return SQLQueryResult(
                success=True,
                rows=[],
                row_count=int(row_count or 0),
                columns=[],
                message=f"Query executed successfully on '{connection_name}', affected {int(row_count or 0)} row(s)",
            ).model_dump()
    finally:
        engine.dispose()


def _run_coroutine_safely(awaitable: Any) -> Any:
    """在同步入口中安全执行协程。

    这里不能假设调用方永远不在事件循环线程里，所以要兼容：
    - 普通同步上下文：直接 `asyncio.run`
    - 已有事件循环的线程：切到独立线程执行
    """

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable)).result()


def _export_rows_to_file(
    *,
    workspace: "TaskWorkspace",
    output_file: str,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> int:
    """把统一 rows 结果导出到 workspace。

    迁入多数据库 adapter 后，不同数据库不一定还能暴露 SQLAlchemy 的 CursorResult。
    因此这里补一个“结果级导出”兜底，保证 output_file 语义仍然成立。
    """

    resolved_path = workspace.resolve_path(output_file, default_dir="output")
    file_ext = Path(output_file).suffix.lower()

    if file_ext == ".csv":
        fieldnames = columns or (list(rows[0].keys()) if rows else [])
        with open(resolved_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return len(rows)

    if file_ext == ".parquet":
        try:
            import pyarrow as pa  # type: ignore[import-not-found]
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as err:
            raise ImportError(
                f"{err}\n"
                "pyarrow is required for Parquet export. "
                "Install it with: pip install pyarrow"
            )
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, resolved_path)
        return len(rows)

    if file_ext in (".json", ".jsonl", ".ndjson"):
        with open(resolved_path, "w", encoding="utf-8") as handle:
            if file_ext == ".json":
                json.dump(rows, handle, ensure_ascii=False, indent=2)
            else:
                for row in rows:
                    print(json.dumps(row, ensure_ascii=False), file=handle)
        return len(rows)

    raise ValueError(
        f"Unsupported file format: {file_ext}. "
        "Supported: .csv (streaming), .parquet (streaming), "
        ".json/.jsonl/.ndjson (streaming JSON Lines)"
    )


def _stream_result_to_file(
    *,
    workspace: "TaskWorkspace",
    output_file: str,
    result: CursorResult,
) -> tuple[int, list[str]]:
    """从 `CursorResult` 流式导出，保留历史大结果集安全边界。"""

    file_ext = Path(output_file).suffix.lower()
    if file_ext == ".csv":
        _, exported_count, columns = _stream_export_to_csv(workspace, output_file, result)
        return exported_count, columns
    if file_ext == ".parquet":
        _, exported_count, columns = _stream_export_to_parquet(
            workspace,
            output_file,
            result,
        )
        return exported_count, columns
    if file_ext in (".json", ".jsonl", ".ndjson"):
        _, exported_count, columns = _stream_export_to_jsonlines(
            workspace,
            output_file,
            result,
        )
        return exported_count, columns
    raise ValueError(
        f"Unsupported file format: {file_ext}. "
        "Supported: .csv (streaming), .parquet (streaming), "
        ".json/.jsonl/.ndjson (streaming JSON Lines)"
    )


def _stream_export_to_csv(
    workspace: "TaskWorkspace",
    file_path: str,
    result: CursorResult,
    batch_size: int = 1000,
) -> tuple[str, int, list[str]]:
    """Streaming export to CSV.

    Returns:
        Tuple of (exported_file_path, row_count, column_names)
    """
    resolved_path = workspace.resolve_path(file_path, default_dir="output")

    # Get column names BEFORE iteration
    columns = list(result.keys())

    row_count = 0
    writer: csv.DictWriter | None = None

    with open(resolved_path, "w", encoding="utf-8", newline="") as f:
        # Fetch in batches
        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break

            # Convert batch to dict format
            batch_dicts = [_row_to_dict(row) for row in batch]

            # Initialize writer on first batch
            if writer is None:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()

            # Write batch to file
            if writer is not None:
                writer.writerows(batch_dicts)
            row_count += len(batch)

    return str(resolved_path), row_count, columns


def _stream_export_to_jsonlines(
    workspace: "TaskWorkspace",
    file_path: str,
    result: CursorResult,
    batch_size: int = 1000,
) -> tuple[str, int, list[str]]:
    """Streaming export to JSON Lines (NDJSON).

    Returns:
        Tuple of (exported_file_path, row_count, column_names)
    """
    resolved_path = workspace.resolve_path(file_path, default_dir="output")

    # Get column names BEFORE iteration
    columns = list(result.keys())

    row_count = 0

    with open(resolved_path, "w", encoding="utf-8") as f:
        # Fetch in batches
        while True:
            batch = result.fetchmany(batch_size)
            if not batch:
                break

            # Convert batch to JSON lines and write
            for row in batch:
                row_dict = _row_to_dict(row)
                print(json.dumps(row_dict, ensure_ascii=False), file=f)
                row_count += 1

    return str(resolved_path), row_count, columns


def _stream_export_to_parquet(
    workspace: "TaskWorkspace",
    file_path: str,
    result: CursorResult,
    batch_size: int = 5000,
) -> tuple[str, int, list[str]]:
    """Streaming export to Parquet.

    Parquet provides excellent compression and preserves data types.

    Returns:
        Tuple of (exported_file_path, row_count, column_names)
    """
    try:
        import pyarrow as pa  # type: ignore[import-not-found]
        import pyarrow.parquet as pq  # type: ignore[import-not-found]
    except ImportError as err:
        raise ImportError(
            f"{err}\n"
            "pyarrow is required for Parquet export. "
            "Install it with: pip install pyarrow"
        )

    resolved_path = workspace.resolve_path(file_path, default_dir="output")

    # Get column names BEFORE iteration
    columns = list(result.keys())

    row_count = 0
    writer = None

    # Fetch in batches
    while True:
        batch = result.fetchmany(batch_size)
        if not batch:
            break

        # Convert batch to dict format
        batch_dicts = [_row_to_dict(row) for row in batch]

        # Create Arrow Table from batch
        table = pa.Table.from_pylist(batch_dicts)

        # Initialize writer with schema from first batch
        if writer is None:
            writer = pq.ParquetWriter(resolved_path, table.schema)

        # Write batch to file
        writer.write_table(table)
        row_count += len(batch)

    # Close writer to finalize file
    if writer:
        writer.close()

    return str(resolved_path), row_count, columns
