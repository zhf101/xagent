"""SQL Brain 的 schema 训练引导工具。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import make_url

from xagent.core.database.adapters import create_adapter_for_type
from xagent.core.database.config import database_connection_config_from_url

from .llm_utils import run_async_sync
from .models import RetrievedDDL


def _format_column_definition(column: dict[str, Any]) -> str:
    name = str(column.get("name") or "").strip()
    col_type = str(column.get("type") or "TEXT").strip() or "TEXT"
    nullable = bool(column.get("nullable", True))
    default = column.get("default")

    parts = [name, col_type]
    parts.append("NULL" if nullable else "NOT NULL")
    if default is not None and str(default).strip():
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


def _table_to_training_ddl(table: dict[str, Any]) -> tuple[str, str] | None:
    table_name = str(table.get("table") or "").strip()
    if not table_name:
        return None

    schema_name = str(table.get("schema") or "").strip()
    qualified_name = (
        f"{schema_name}.{table_name}"
        if schema_name and schema_name not in {"main", "public"}
        else table_name
    )
    columns = table.get("columns") or []
    if not isinstance(columns, list) or not columns:
        return None

    column_lines = [
        f"  {_format_column_definition(column)}"
        for column in columns
        if str(column.get("name") or "").strip()
    ]
    if not column_lines:
        return None

    ddl = "CREATE TABLE " + qualified_name + " (\n" + ",\n".join(column_lines) + "\n);"
    return table_name, ddl


def load_schema_training_snippets(
    *,
    db_url: str,
    db_type: str | None,
    system_short: str | None,
    max_tables: int = 50,
) -> list[RetrievedDDL]:
    """从 datasource 连接只读拉取 schema，并转换成 SQL Brain 可训练的 DDL 片段。"""

    adapter = None
    try:
        url = make_url(db_url)
        config = database_connection_config_from_url(url, read_only=True)
        resolved_db_type = db_type or config.db_type
        adapter = create_adapter_for_type(resolved_db_type, config)
        run_async_sync(adapter.connect())
        schema = run_async_sync(adapter.get_schema())
    except Exception:
        return []
    finally:
        if adapter is not None:
            try:
                run_async_sync(adapter.disconnect())
            except Exception:
                pass

    tables = schema.get("tables") or []
    snippets: list[RetrievedDDL] = []
    for table in tables[: max(max_tables, 0)]:
        if not isinstance(table, dict):
            continue
        converted = _table_to_training_ddl(table)
        if converted is None:
            continue
        table_name, ddl = converted
        snippets.append(
            RetrievedDDL(
                table_name=table_name,
                ddl=ddl,
                system_short=system_short,
                db_type=db_type or schema.get("databaseType"),
            )
        )

    return snippets
