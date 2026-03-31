"""
`Resource Plane / SQL Schema Provider`（资源平面 / SQL Schema 提供器）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`（资源平面）
- 在你的设计里：SQL 真实资源旁边的 schema 读取辅助件

这个文件负责什么：
- 从显式注入的 schema 快照读取 DDL
- 在确有必要时，从受控数据库连接提取只读 schema 信息
- 把分散格式统一转换成 DDL 片段，供 verifier / generator 使用

这个文件不负责什么：
- 不生成 SQL
- 不做审批判断
- 不执行正式业务 SQL
- 不决定是否可以执行下一步动作

设计原则：
- 先吃“显式注入的 schema 快照”，保证任务隔离和可审计
- 只有在上游没有给 schema 时，才退到数据库反射读取
- 输出始终是稳定的 DDL 字符串列表，避免下游依赖数据库驱动细节
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from ...database.adapters import create_adapter_for_type
from ...database.config import database_connection_config_from_url
from .sql_datasource_resolver import SqlDatasourceResolver
from .sql_resource_definition import parse_sql_resource_metadata


class SqlSchemaProvider:
    """
    `SqlSchemaProvider`（SQL Schema 提供器）。

    它是 SQL Brain 的“schema 输入收敛器”：
    上游无论给的是 DDL、表结构快照、连接名还是 URL，
    最终都会被转换成统一的 DDL 片段列表。
    """

    def __init__(
        self,
        datasource_resolver: SqlDatasourceResolver | None = None,
    ) -> None:
        self.datasource_resolver = datasource_resolver or SqlDatasourceResolver()

    def resolve_schema_ddl(
        self,
        *,
        metadata: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        max_tables: int = 50,
    ) -> list[str]:
        """
        解析当前 SQL 动作可见的 schema DDL 集合。

        解析顺序：
        1. 显式注入的 DDL / schema 快照
        2. 连接信息对应的数据库反射
        """

        metadata = metadata or {}
        params = params or {}

        inline_schema = self._extract_inline_schema_ddl(metadata, params)
        if inline_schema:
            return inline_schema[: max(max_tables, 0)]

        resolved_source = self.datasource_resolver.resolve(
            metadata=metadata,
            params=params,
        )
        parsed_metadata = parse_sql_resource_metadata(metadata)

        connection_name = self._coalesce_str(
            params.get("connection_name"),
            parsed_metadata.datasource.connection_name,
            parsed_metadata.datasource.datasource_name,
            resolved_source.get("connection_name"),
        )
        db_url = self._coalesce_str(
            params.get("db_url"),
            params.get("database_url"),
            parsed_metadata.datasource.db_url,
            resolved_source.get("db_url"),
        )
        if not connection_name and not db_url:
            return []

        return self.load_schema_ddl_from_connection(
            connection_name=connection_name,
            db_url=db_url,
            max_tables=max_tables,
        )

    def load_schema_ddl_from_connection(
        self,
        *,
        connection_name: str | None = None,
        db_url: str | None = None,
        max_tables: int = 50,
    ) -> list[str]:
        """
        从受控连接只读拉取 schema，并转成 DDL 片段。

        Phase 1 这里刻意只做 schema 反射，不读取真实业务数据，
        从而把数据库访问严格收缩在“结构信息”层面。
        """

        resolved_url = self._resolve_database_url(
            connection_name=connection_name,
            db_url=db_url,
        )
        if resolved_url is None:
            return []

        try:
            config = database_connection_config_from_url(make_url(resolved_url), read_only=True)
            try:
                adapter = create_adapter_for_type(config.db_type, config)
            except ValueError:
                return self._reflect_schema_via_sqlalchemy(resolved_url)[: max(max_tables, 0)]
            schema_snapshot = self._run_async(adapter.get_schema())
        except Exception:
            return []

        return self._convert_snapshot_to_ddl(schema_snapshot)[: max(max_tables, 0)]

    def _extract_inline_schema_ddl(
        self,
        metadata: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> list[str]:
        """
        优先解析上游已经显式注入的 schema 数据。

        支持的输入形态：
        - `schema_ddl`: list[str]
        - `ddl_snippets`: list[str | {"ddl": "..."}]
        - `schema_snapshot.tables`: list[table-dict]
        """

        parsed_metadata = parse_sql_resource_metadata(metadata)
        direct_candidates = [
            parsed_metadata.sql_context.schema_ddl,
            params.get("schema_ddl"),
            parsed_metadata.extra.get("ddl_snippets"),
            params.get("ddl_snippets"),
        ]
        for candidate in direct_candidates:
            ddl_list = self._normalize_ddl_list(candidate)
            if ddl_list:
                return ddl_list

        snapshot_candidates = [
            parsed_metadata.extra.get("schema_snapshot"),
            params.get("schema_snapshot"),
        ]
        for snapshot in snapshot_candidates:
            converted = self._convert_snapshot_to_ddl(snapshot)
            if converted:
                return converted

        return []

    def _normalize_ddl_list(self, value: Any) -> list[str]:
        """
        把多种 DDL 容器统一收敛成纯字符串列表。
        """

        if not isinstance(value, list):
            return []

        normalized: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
                continue
            if isinstance(item, Mapping):
                ddl = item.get("ddl")
                if isinstance(ddl, str) and ddl.strip():
                    normalized.append(ddl.strip())
        return normalized

    def _convert_snapshot_to_ddl(self, snapshot: Any) -> list[str]:
        """
        把结构化 schema 快照转换成 DDL 片段。
        """

        if not isinstance(snapshot, Mapping):
            return []
        tables = snapshot.get("tables")
        if not isinstance(tables, list):
            return []

        ddl_snippets: list[str] = []
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            table_name = str(table.get("table") or table.get("table_name") or "").strip()
            if not table_name:
                continue
            schema_name = str(table.get("schema") or "").strip() or None
            columns = table.get("columns")
            if not isinstance(columns, list) or not columns:
                continue
            ddl_snippets.append(
                self._build_table_ddl(
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                )
            )
        return ddl_snippets

    def _build_table_ddl(
        self,
        *,
        schema_name: str | None,
        table_name: str,
        columns: Iterable[Mapping[str, Any]],
    ) -> str:
        """
        把单表列信息转成训练/校验友好的 DDL 字符串。
        """

        qualified_name = table_name
        if schema_name and schema_name not in {"main", "public"}:
            qualified_name = f"{schema_name}.{table_name}"

        column_lines: list[str] = []
        for column in columns:
            column_name = str(column.get("name") or "").strip()
            if not column_name:
                continue
            column_type = str(column.get("type") or "TEXT").strip() or "TEXT"
            nullable = bool(column.get("nullable", True))
            default = column.get("default")

            parts = [column_name, column_type, "NULL" if nullable else "NOT NULL"]
            if default is not None and str(default).strip():
                parts.append(f"DEFAULT {default}")
            column_lines.append("  " + " ".join(parts))

        if not column_lines:
            return f"CREATE TABLE {qualified_name} ();"

        return "CREATE TABLE " + qualified_name + " (\n" + ",\n".join(column_lines) + "\n);"

    def _resolve_database_url(
        self,
        *,
        connection_name: str | None,
        db_url: str | None,
    ) -> str | None:
        """
        优先解析显式 URL；没有时再从约定环境变量读取。
        """

        if isinstance(db_url, str) and db_url.strip():
            return db_url.strip()
        if isinstance(connection_name, str) and connection_name.strip():
            env_key = f"XAGENT_EXTERNAL_DB_{connection_name.strip().upper()}"
            url = os.getenv(env_key)
            if isinstance(url, str) and url.strip():
                return url.strip()
        return None

    def _run_async(self, awaitable: Any) -> Any:
        """在同步 schema provider 中安全执行 adapter 的异步接口。

        这里不能直接 `asyncio.run()`，因为上游经常已经运行在事件循环线程里。
        因此把 awaitable 丢到独立线程中执行，避免触发
        `asyncio.run() cannot be called from a running event loop`。
        """

        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(awaitable)).result()

    def _reflect_schema_via_sqlalchemy(self, db_url: str) -> list[str]:
        """为历史 SQLAlchemy 方言保留 schema 反射兼容路径。"""

        engine = create_engine(db_url, future=True)
        ddl_snippets: list[str] = []
        try:
            inspector = inspect(engine)
            schema_names = inspector.get_schema_names() or []
            preferred_schemas = [
                schema_name
                for schema_name in schema_names
                if schema_name not in {"information_schema", "pg_catalog", "sys"}
            ] or [None]

            for schema_name in preferred_schemas:
                table_names = inspector.get_table_names(schema=schema_name)
                for table_name in table_names:
                    ddl_snippets.append(
                        self._build_table_ddl(
                            schema_name=schema_name,
                            table_name=table_name,
                            columns=inspector.get_columns(table_name, schema=schema_name),
                        )
                    )
        finally:
            engine.dispose()

        return ddl_snippets

    def _coalesce_str(self, *values: Any) -> str | None:
        """
        返回第一个非空字符串。
        """

        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
