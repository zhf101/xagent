"""Vanna schema 采集服务。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ...core.database.adapters import create_adapter_for_type
from ...core.database.config import database_connection_config_from_url
from ...web.models.text2sql import Text2SQLDatabase
from ...web.models.vanna import (
    VannaHarvestJobStatus,
    VannaSchemaColumn,
    VannaSchemaHarvestJob,
    VannaSchemaTable,
    VannaSchemaTableStatus,
)
from .contracts import HarvestCommitResult, HarvestPreviewResult, HarvestTablePreview
from .errors import VannaDatasourceNotFoundError
from .knowledge_base_service import KnowledgeBaseService


class SchemaHarvestService:
    """从 Text2SQL 数据源采集 schema 结构事实。"""

    def __init__(self, db: Session):
        self.db = db
        self.kb_service = KnowledgeBaseService(db)

    def _get_datasource(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
    ) -> Text2SQLDatabase:
        datasource = (
            self.db.query(Text2SQLDatabase)
            .filter(
                Text2SQLDatabase.id == int(datasource_id),
                Text2SQLDatabase.user_id == int(owner_user_id),
            )
            .first()
        )
        if datasource is None:
            raise VannaDatasourceNotFoundError(
                f"Datasource {datasource_id} was not found"
            )
        return datasource

    async def _load_schema_snapshot(
        self,
        *,
        datasource: Text2SQLDatabase,
    ) -> dict[str, Any]:
        config = database_connection_config_from_url(
            make_url(datasource.url),
            read_only=datasource.read_only,
        )
        adapter = create_adapter_for_type(datasource.type.value, config)
        await adapter.connect()
        try:
            return await adapter.get_schema()
        finally:
            await adapter.disconnect()

    def _normalize_name_set(self, names: list[str] | None) -> set[str]:
        return {
            name.strip()
            for name in names or []
            if isinstance(name, str) and name.strip()
        }

    def _filter_tables(
        self,
        schema_snapshot: dict[str, Any],
        *,
        schema_names: list[str] | None = None,
        table_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        selected_schemas = self._normalize_name_set(schema_names)
        selected_tables = self._normalize_name_set(table_names)
        filtered: list[dict[str, Any]] = []

        for table in list(schema_snapshot.get("tables") or []):
            if not isinstance(table, dict):
                continue
            schema_name = table.get("schema")
            table_name = table.get("table")
            if selected_schemas and schema_name not in selected_schemas:
                continue
            if selected_tables and table_name not in selected_tables:
                continue
            filtered.append(table)
        return filtered

    def _classify_default_kind(self, default_value: Any) -> str:
        if default_value is None:
            return "none"
        if not isinstance(default_value, str):
            return "literal"

        text = default_value.strip()
        if not text:
            return "none"
        if "nextval" in text.lower():
            return "sequence"
        if "(" in text and ")" in text:
            return "function"
        if any(token in text for token in ["+", "-", "*", "/", "::"]):
            return "expression"
        return "literal"

    def _classify_value_source_kind(
        self,
        *,
        column: dict[str, Any],
        is_primary_key: bool,
        is_foreign_key: bool,
    ) -> str:
        data_type = str(column.get("type") or "").lower()
        if is_primary_key:
            return "generated"
        if is_foreign_key:
            return "foreign_key"
        if "bool" in data_type:
            return "boolean"
        return "unknown"

    def _build_table_content_hash(self, table: dict[str, Any]) -> str:
        payload = {
            "schema": table.get("schema"),
            "table": table.get("table"),
            "comment": table.get("comment"),
            "columns": table.get("columns"),
            "primary_keys": table.get("primary_keys"),
            "foreign_keys": table.get("foreign_keys"),
            "indexes": table.get("indexes"),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _build_column_content_hash(
        self,
        *,
        schema_name: str | None,
        table_name: str,
        column: dict[str, Any],
    ) -> str:
        payload = {
            "schema": schema_name,
            "table": table_name,
            "column": column,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    async def preview_harvest(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        schema_names: list[str] | None = None,
        table_names: list[str] | None = None,
    ) -> HarvestPreviewResult:
        datasource = self._get_datasource(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
        )
        schema_snapshot = await self._load_schema_snapshot(datasource=datasource)
        filtered_tables = self._filter_tables(
            schema_snapshot,
            schema_names=schema_names,
            table_names=table_names,
        )

        previews = [
            HarvestTablePreview(
                schema_name=table.get("schema"),
                table_name=str(table.get("table")),
                column_count=len(list(table.get("columns") or [])),
                primary_keys=list(table.get("primary_keys") or []),
                foreign_key_count=len(list(table.get("foreign_keys") or [])),
                table_comment=table.get("comment"),
            )
            for table in filtered_tables
        ]

        return HarvestPreviewResult(
            datasource_id=int(datasource.id),
            system_short=datasource.system_short,
            env=datasource.env,
            db_type=datasource.type.value,
            family=schema_snapshot.get("family"),
            selected_schema_names=sorted(
                {
                    table.schema_name
                    for table in previews
                    if isinstance(table.schema_name, str) and table.schema_name
                }
            ),
            selected_table_names=[table.table_name for table in previews],
            tables=previews,
        )

    async def commit_harvest(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        owner_user_name: str | None = None,
        schema_names: list[str] | None = None,
        table_names: list[str] | None = None,
    ) -> HarvestCommitResult:
        datasource = self._get_datasource(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
        )
        kb = self.kb_service.get_or_create_default_kb(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
            owner_user_name=owner_user_name,
        )
        job = VannaSchemaHarvestJob(
            kb_id=int(kb.id),
            datasource_id=int(datasource.id),
            system_short=datasource.system_short,
            env=datasource.env,
            status=VannaHarvestJobStatus.RUNNING.value,
            harvest_scope="tables"
            if table_names
            else "schemas"
            if schema_names
            else "all",
            schema_names_json=list(schema_names or []),
            table_names_json=list(table_names or []),
            create_user_id=int(owner_user_id),
            create_user_name=owner_user_name,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        try:
            schema_snapshot = await self._load_schema_snapshot(datasource=datasource)
            filtered_tables = self._filter_tables(
                schema_snapshot,
                schema_names=schema_names,
                table_names=table_names,
            )

            table_count = 0
            column_count = 0

            for table in filtered_tables:
                schema_name = table.get("schema")
                table_name = str(table.get("table"))
                existing_rows = (
                    self.db.query(VannaSchemaTable)
                    .filter(
                        VannaSchemaTable.kb_id == int(kb.id),
                        VannaSchemaTable.schema_name == schema_name,
                        VannaSchemaTable.table_name == table_name,
                        VannaSchemaTable.status == VannaSchemaTableStatus.ACTIVE.value,
                    )
                    .all()
                )
                for existing_row in existing_rows:
                    existing_row.status = VannaSchemaTableStatus.STALE.value

                table_row = VannaSchemaTable(
                    kb_id=int(kb.id),
                    datasource_id=int(datasource.id),
                    harvest_job_id=int(job.id),
                    system_short=datasource.system_short,
                    env=datasource.env,
                    catalog_name=table.get("catalog"),
                    schema_name=schema_name,
                    table_name=table_name,
                    table_type=table.get("table_type"),
                    table_comment=table.get("comment"),
                    table_ddl=table.get("ddl"),
                    primary_key_json=list(table.get("primary_keys") or []),
                    foreign_keys_json=list(table.get("foreign_keys") or []),
                    indexes_json=list(table.get("indexes") or []),
                    constraints_json=list(table.get("constraints") or []),
                    content_hash=self._build_table_content_hash(table),
                    status=VannaSchemaTableStatus.ACTIVE.value,
                )
                self.db.add(table_row)
                self.db.flush()
                table_count += 1

                foreign_key_map: dict[str, tuple[str | None, str | None]] = {}
                for foreign_key in list(table.get("foreign_keys") or []):
                    referred_table = foreign_key.get("referred_table")
                    referred_columns = list(foreign_key.get("referred_columns") or [])
                    constrained_columns = list(
                        foreign_key.get("constrained_columns") or []
                    )
                    for idx, column_name in enumerate(constrained_columns):
                        referred_column = (
                            referred_columns[idx]
                            if idx < len(referred_columns)
                            else referred_columns[0]
                            if referred_columns
                            else None
                        )
                        foreign_key_map[str(column_name)] = (
                            referred_table,
                            referred_column,
                        )

                for position, column in enumerate(
                    list(table.get("columns") or []), start=1
                ):
                    column_name = str(column.get("name"))
                    is_primary_key = column_name in list(
                        table.get("primary_keys") or []
                    )
                    is_foreign_key = column_name in foreign_key_map
                    foreign_table, foreign_column = foreign_key_map.get(
                        column_name, (None, None)
                    )
                    column_row = VannaSchemaColumn(
                        table_id=int(table_row.id),
                        kb_id=int(kb.id),
                        datasource_id=int(datasource.id),
                        system_short=datasource.system_short,
                        env=datasource.env,
                        schema_name=schema_name,
                        table_name=table_name,
                        column_name=column_name,
                        ordinal_position=position,
                        data_type=str(column.get("type") or ""),
                        udt_name=str(column.get("type") or ""),
                        is_nullable=bool(column.get("nullable"))
                        if column.get("nullable") is not None
                        else None,
                        default_raw=str(column.get("default"))
                        if column.get("default") is not None
                        else None,
                        default_kind=self._classify_default_kind(column.get("default")),
                        column_comment=column.get("comment"),
                        is_primary_key=is_primary_key,
                        is_foreign_key=is_foreign_key,
                        foreign_table_name=foreign_table,
                        foreign_column_name=foreign_column,
                        value_source_kind=self._classify_value_source_kind(
                            column=column,
                            is_primary_key=is_primary_key,
                            is_foreign_key=is_foreign_key,
                        ),
                        content_hash=self._build_column_content_hash(
                            schema_name=schema_name,
                            table_name=table_name,
                            column=column,
                        ),
                    )
                    self.db.add(column_row)
                    column_count += 1

            job.status = VannaHarvestJobStatus.COMPLETED.value
            job.result_payload_json = {
                "table_count": table_count,
                "column_count": column_count,
                "schema_names": sorted(
                    {
                        table.get("schema")
                        for table in filtered_tables
                        if isinstance(table.get("schema"), str) and table.get("schema")
                    }
                ),
                "table_names": [str(table.get("table")) for table in filtered_tables],
            }
            self.db.commit()
            self.db.refresh(job)
            return HarvestCommitResult(
                job_id=int(job.id),
                kb_id=int(kb.id),
                table_count=table_count,
                column_count=column_count,
                summary=dict(job.result_payload_json or {}),
            )
        except Exception as exc:
            self.db.rollback()
            job = (
                self.db.query(VannaSchemaHarvestJob)
                .filter(VannaSchemaHarvestJob.id == int(job.id))
                .first()
            )
            if job is not None:
                job.status = VannaHarvestJobStatus.FAILED.value
                job.error_message = str(exc)
                self.db.commit()
            raise
