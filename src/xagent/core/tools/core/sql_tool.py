"""SQL Tool for xagent。

数据库连接通过环境变量提供：
`XAGENT_EXTERNAL_DB_<NAME>=<connection_url>`

现在 sql_tool 不再自己维护一套分裂的执行链，而是统一走
`core.database.adapters`，这样 Text2SQL、datamakepool、通用 SQL 工具
会共享同一套数据库类型规范与执行适配层。

注意：
- 对 SQL 数据库，query 仍然是普通 SQL 文本
- 对 MongoDB / Redis 这类非 SQL 数据库，query 需要传 JSON 命令协议
"""

import asyncio
import csv
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import URL
from sqlalchemy.engine import Row, make_url

from ...database.adapters import create_adapter_for_type
from ...database.config import database_connection_config_from_url
from ...database.types import normalize_database_type

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
    # Extract driver name from URL (e.g., "postgresql+asyncpg" -> "postgresql")
    raw_type = url.drivername.split("+")[0]
    return normalize_database_type(raw_type)


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
    adapter = create_adapter_for_type(config.db_type, config)
    result = asyncio.run(adapter.execute_query(query))

    if output_file and workspace:
        file_ext = output_file.rsplit(".", 1)[-1].lower() if "." in output_file else ""
        if file_ext == "csv":
            exported_count, columns = _export_rows_to_csv(
                workspace, output_file, result.rows
            )
        elif file_ext == "parquet":
            exported_count, columns = _export_rows_to_parquet(
                workspace, output_file, result.rows
            )
        elif file_ext in {"json", "jsonl", "ndjson"}:
            exported_count, columns = _export_rows_to_jsonlines(
                workspace, output_file, result.rows
            )
        else:
            raise ValueError(
                "Unsupported file format. Supported: .csv, .parquet, .json/.jsonl/.ndjson"
            )
        return SQLQueryResult(
            success=True,
            rows=[],
            row_count=exported_count,
            columns=columns,
            message=f"Query executed successfully on '{connection_name}', exported {exported_count} row(s) to {output_file}",
        ).model_dump()

    columns = list(result.rows[0].keys()) if result.rows else []
    row_count = (
        result.affected_rows
        if result.affected_rows is not None
        else len(result.rows)
    )
    action = "returned" if result.rows else "affected"
    return SQLQueryResult(
        success=True,
        rows=result.rows,
        row_count=row_count or 0,
        columns=columns,
        message=f"Query executed successfully on '{connection_name}', {action} {row_count or 0} row(s)",
    ).model_dump()


def _export_rows_to_csv(
    workspace: "TaskWorkspace",
    file_path: str,
    rows: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """把结构化行结果导出为 CSV。"""
    resolved_path = workspace.resolve_path(file_path, default_dir="output")
    columns = list(rows[0].keys()) if rows else []

    with open(resolved_path, "w", encoding="utf-8", newline="") as f:
        if columns:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    return len(rows), columns


def _export_rows_to_jsonlines(
    workspace: "TaskWorkspace",
    file_path: str,
    rows: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """把结构化行结果导出为 JSON Lines。"""
    resolved_path = workspace.resolve_path(file_path, default_dir="output")
    columns = list(rows[0].keys()) if rows else []

    with open(resolved_path, "w", encoding="utf-8") as f:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False), file=f)

    return len(rows), columns


def _export_rows_to_parquet(
    workspace: "TaskWorkspace",
    file_path: str,
    rows: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """把结构化行结果导出为 Parquet。"""
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
    columns = list(rows[0].keys()) if rows else []
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, resolved_path)
    return len(rows), columns
