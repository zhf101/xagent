"""把结构事实转成可读的 schema summary。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .schema_annotation_service import (
    SchemaAnnotationService,
    annotation_key_for_column,
    effective_list_value,
    effective_text_value,
)
from ...web.models.vanna import (
    VannaSchemaColumn,
    VannaSchemaColumnAnnotation,
    VannaSchemaTable,
    VannaTrainingEntry,
    VannaTrainingLifecycleStatus,
    VannaTrainingQualityStatus,
)


class SchemaSummaryService:
    """从表/字段事实生成 schema summary 训练条目。"""

    def __init__(self, db: Session):
        self.db = db
        self.annotation_service = SchemaAnnotationService(db)

    def build_table_summary(
        self,
        *,
        table_row: VannaSchemaTable,
        column_rows: list[VannaSchemaColumn],
        annotation_map: dict[
            tuple[int, str, str, str], VannaSchemaColumnAnnotation
        ] | None = None,
    ) -> str:
        lines = [f"表 {table_row.schema_name or 'default'}.{table_row.table_name}:"]

        if table_row.table_comment:
            lines.append(f"- 表用途: {table_row.table_comment}")

        primary_keys = [col.column_name for col in column_rows if col.is_primary_key]
        if primary_keys:
            lines.append(f"- 主键: {', '.join(primary_keys)}")

        foreign_keys = [
            col
            for col in column_rows
            if col.is_foreign_key and col.foreign_table_name and col.foreign_column_name
        ]
        for foreign_key in foreign_keys:
            lines.append(
                f"- 关联字段: {foreign_key.column_name} -> "
                f"{foreign_key.foreign_table_name}.{foreign_key.foreign_column_name}"
            )

        for column in column_rows:
            annotation = (annotation_map or {}).get(annotation_key_for_column(column))
            effective_default = effective_text_value(
                annotation.default_value_override if annotation else None,
                column.default_raw,
            )
            effective_allowed_values = effective_list_value(
                annotation.allowed_values_override_json if annotation else None,
                list(column.allowed_values_json or []),
            )
            effective_comment = effective_text_value(
                annotation.comment_override if annotation else None,
                column.column_comment,
            )
            business_description = (
                annotation.business_description if annotation else None
            )
            tags: list[str] = []
            if column.value_source_kind == "boolean":
                tags.append("布尔字段")
            if effective_default:
                tags.append(f"默认值 {effective_default}")
            if effective_allowed_values:
                tags.append(f"可选值 {list(effective_allowed_values)}")
            if effective_comment:
                tags.append(effective_comment)
            if business_description:
                tags.append(f"业务说明 {business_description}")
            if tags:
                lines.append(f"- 字段 {column.column_name}: {'，'.join(tags)}")

        return "\n".join(lines)

    def create_schema_summary_entry(
        self,
        *,
        table_row: VannaSchemaTable,
        create_user_id: int,
        create_user_name: str | None = None,
        lifecycle_status: str = VannaTrainingLifecycleStatus.CANDIDATE.value,
        quality_status: str = VannaTrainingQualityStatus.UNVERIFIED.value,
    ) -> VannaTrainingEntry:
        column_rows = (
            self.db.query(VannaSchemaColumn)
            .filter(VannaSchemaColumn.table_id == int(table_row.id))
            .order_by(
                VannaSchemaColumn.ordinal_position.asc(), VannaSchemaColumn.id.asc()
            )
            .all()
        )
        annotation_map = self.annotation_service.build_annotation_map_for_columns(
            column_rows
        )
        summary_text = self.build_table_summary(
            table_row=table_row,
            column_rows=column_rows,
            annotation_map=annotation_map,
        )
        entry_code = (
            f"schema-summary:"
            f"{int(table_row.kb_id)}:"
            f"{table_row.schema_name or 'default'}:"
            f"{table_row.table_name}:"
            f"{table_row.content_hash or int(table_row.id)}"
        )
        entry = (
            self.db.query(VannaTrainingEntry)
            .filter(VannaTrainingEntry.entry_code == entry_code)
            .first()
        )
        if entry is None:
            entry = VannaTrainingEntry(
                kb_id=int(table_row.kb_id),
                datasource_id=int(table_row.datasource_id),
                system_short=table_row.system_short,
                env=table_row.env,
                entry_code=entry_code,
                entry_type="schema_summary",
                source_kind="bootstrap_schema",
                source_ref=f"table:{int(table_row.id)}",
                lifecycle_status=lifecycle_status,
                quality_status=quality_status,
                title=f"{table_row.schema_name or 'default'}.{table_row.table_name}",
                doc_text=summary_text,
                schema_name=table_row.schema_name,
                table_name=table_row.table_name,
                create_user_id=int(create_user_id),
                create_user_name=create_user_name,
                content_hash=table_row.content_hash,
            )
            self.db.add(entry)
        else:
            entry.doc_text = summary_text
            entry.content_hash = table_row.content_hash
            entry.lifecycle_status = lifecycle_status
            entry.quality_status = quality_status
            entry.create_user_id = int(create_user_id)
            entry.create_user_name = create_user_name

        self.db.commit()
        self.db.refresh(entry)
        return entry
