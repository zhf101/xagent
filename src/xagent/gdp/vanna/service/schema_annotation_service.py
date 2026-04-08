"""结构事实人工补充/覆写服务。

数据库原生注释往往不完整，或者完全是技术命名。这个模块允许平台补充一层
“更贴近业务语义”的 annotation，并在摘要生成时覆盖原始结构事实。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from xagent.gdp.vanna.model.vanna import VannaSchemaColumn, VannaSchemaColumnAnnotation


def normalize_schema_name(schema_name: str | None) -> str:
    """统一 schema 名归一化策略。"""

    return (schema_name or "").strip()


def annotation_key(
    *,
    kb_id: int,
    schema_name: str | None,
    table_name: str,
    column_name: str,
) -> tuple[int, str, str, str]:
    """构造 annotation 的稳定键。"""

    return (
        int(kb_id),
        normalize_schema_name(schema_name),
        str(table_name),
        str(column_name),
    )


def annotation_key_for_column(
    column_row: VannaSchemaColumn,
) -> tuple[int, str, str, str]:
    """从字段行对象构造 annotation 键。"""

    return annotation_key(
        kb_id=int(column_row.kb_id),
        schema_name=column_row.schema_name,
        table_name=str(column_row.table_name),
        column_name=str(column_row.column_name),
    )


def effective_text_value(override: str | None, raw: str | None) -> str | None:
    """优先使用人工覆写文本，缺失时回退原始值。"""

    return raw if override is None else override


def effective_list_value(
    override: list[str] | None,
    raw: list[str] | None,
) -> list[str]:
    """优先使用人工覆写列表，缺失时回退原始值。"""

    if override is None:
        return list(raw or [])
    return list(override or [])


def sanitize_text(value: str | None) -> str | None:
    """清洗单个文本输入。"""

    if value is None:
        return None
    return value.strip()


def sanitize_string_list(values: Iterable[str] | None) -> list[str] | None:
    """清洗字符串列表，去空白和空项。"""

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
        """批量读取字段 annotation，并整理成按字段键索引的映射。"""

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
        """读取单字段当前生效的 annotation。"""

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
        """为单字段新增或更新 annotation。

        状态影响：
        - 新建时会落库一条 annotation
        - 更新时只覆盖人工可维护字段，不改原始结构快照
        """

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

