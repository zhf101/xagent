"""结构事实人工补充/覆写服务。"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from xagent.gdp.vanna.model.vanna import VannaSchemaColumn, VannaSchemaColumnAnnotation


def normalize_schema_name(schema_name: str | None) -> str:
    return (schema_name or "").strip()


def annotation_key(
    *,
    kb_id: int,
    schema_name: str | None,
    table_name: str,
    column_name: str,
) -> tuple[int, str, str, str]:
    return (
        int(kb_id),
        normalize_schema_name(schema_name),
        str(table_name),
        str(column_name),
    )


def annotation_key_for_column(
    column_row: VannaSchemaColumn,
) -> tuple[int, str, str, str]:
    return annotation_key(
        kb_id=int(column_row.kb_id),
        schema_name=column_row.schema_name,
        table_name=str(column_row.table_name),
        column_name=str(column_row.column_name),
    )


def effective_text_value(override: str | None, raw: str | None) -> str | None:
    return raw if override is None else override


def effective_list_value(
    override: list[str] | None,
    raw: list[str] | None,
) -> list[str]:
    if override is None:
        return list(raw or [])
    return list(override or [])


def sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def sanitize_string_list(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized: list[str] = []
    for value in values:
        item = str(value).strip()
        if item:
            normalized.append(item)
    return normalized


class SchemaAnnotationService:
    """结构事实人工补充/覆写服务。"""

    def __init__(self, db: Session):
        self.db = db

    def build_annotation_map_for_columns(
        self,
        column_rows: list[VannaSchemaColumn],
    ) -> dict[tuple[int, str, str, str], VannaSchemaColumnAnnotation]:
        if not column_rows:
            return {}

        kb_ids = sorted({int(row.kb_id) for row in column_rows})
        table_names = sorted({str(row.table_name) for row in column_rows})
        column_names = sorted({str(row.column_name) for row in column_rows})
        rows = (
            self.db.query(VannaSchemaColumnAnnotation)
            .filter(VannaSchemaColumnAnnotation.kb_id.in_(kb_ids))
            .filter(VannaSchemaColumnAnnotation.table_name.in_(table_names))
            .filter(VannaSchemaColumnAnnotation.column_name.in_(column_names))
            .all()
        )
        return {
            annotation_key(
                kb_id=int(row.kb_id),
                schema_name=row.schema_name,
                table_name=str(row.table_name),
                column_name=str(row.column_name),
            ): row
            for row in rows
        }

    def get_annotation_for_column(
        self,
        column_row: VannaSchemaColumn,
    ) -> VannaSchemaColumnAnnotation | None:
        return (
            self.db.query(VannaSchemaColumnAnnotation)
            .filter(
                VannaSchemaColumnAnnotation.kb_id == int(column_row.kb_id),
                VannaSchemaColumnAnnotation.schema_name
                == normalize_schema_name(column_row.schema_name),
                VannaSchemaColumnAnnotation.table_name == str(column_row.table_name),
                VannaSchemaColumnAnnotation.column_name == str(column_row.column_name),
            )
            .first()
        )

    def upsert_for_column(
        self,
        *,
        column_row: VannaSchemaColumn,
        business_description: str | None,
        comment_override: str | None,
        default_value_override: str | None,
        allowed_values_override_json: list[str] | None,
        sample_values_override_json: list[str] | None,
        update_source: str,
        user_id: int,
        user_name: str | None,
    ) -> VannaSchemaColumnAnnotation:
        row = self.get_annotation_for_column(column_row)
        if row is None:
            row = VannaSchemaColumnAnnotation(
                kb_id=int(column_row.kb_id),
                datasource_id=int(column_row.datasource_id),
                system_short=str(column_row.system_short),
                env=str(column_row.env),
                schema_name=normalize_schema_name(column_row.schema_name),
                table_name=str(column_row.table_name),
                column_name=str(column_row.column_name),
                create_user_id=int(user_id),
                create_user_name=user_name,
                updated_by_user_id=int(user_id),
                updated_by_user_name=user_name,
                update_source=update_source,
            )
            self.db.add(row)

        row.business_description = sanitize_text(business_description)
        row.comment_override = comment_override
        row.default_value_override = default_value_override
        row.allowed_values_override_json = sanitize_string_list(
            allowed_values_override_json
        )
        row.sample_values_override_json = sanitize_string_list(
            sample_values_override_json
        )
        row.update_source = str(update_source or "manual")
        row.updated_by_user_id = int(user_id)
        row.updated_by_user_name = user_name

        self.db.commit()
        self.db.refresh(row)
        return row

