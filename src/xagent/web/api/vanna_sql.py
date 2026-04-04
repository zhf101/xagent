"""Vanna SQL 治理与 ask API。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.vanna.ask_service import AskService
from ...core.vanna.index_service import IndexService
from ...core.vanna.knowledge_base_service import KnowledgeBaseService
from ...core.vanna.query_service import QueryService
from ...core.vanna.schema_harvest_service import SchemaHarvestService
from ...core.vanna.sql_assets import SqlAssetService
from ...core.vanna.train_service import TrainService
from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User
from ..models.vanna import (
    VannaAskRun,
    VannaEmbeddingChunk,
    VannaKnowledgeBase,
    VannaSqlAsset,
    VannaSqlAssetVersion,
    VannaSchemaColumn,
    VannaSchemaHarvestJob,
    VannaSchemaTable,
    VannaTrainingEntry,
)

vanna_router = APIRouter(prefix="/api/vanna", tags=["vanna"])


class KnowledgeBaseCreateRequest(BaseModel):
    """创建或更新默认知识库请求。"""

    datasource_id: int = Field(..., ge=1)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    default_top_k_sql: int | None = Field(default=None, ge=1, le=50)
    default_top_k_schema: int | None = Field(default=None, ge=1, le=50)
    default_top_k_doc: int | None = Field(default=None, ge=1, le=50)
    embedding_model: str | None = Field(default=None, max_length=128)
    llm_model: str | None = Field(default=None, max_length=128)


class SchemaHarvestRequest(BaseModel):
    """Schema 采集请求。"""

    datasource_id: int = Field(..., ge=1)
    schema_names: list[str] = Field(default_factory=list)
    table_names: list[str] = Field(default_factory=list)


class TrainRequest(BaseModel):
    """Vanna 训练请求。"""

    datasource_id: int = Field(..., ge=1)
    question: str | None = None
    sql: str | None = None
    documentation: str | None = None
    title: str | None = None
    bootstrap_schema: bool = False
    publish: bool = True


class AskRequest(BaseModel):
    """Vanna ask 请求。"""

    datasource_id: int = Field(..., ge=1)
    kb_id: int | None = Field(default=None, ge=1)
    task_id: int | None = Field(default=None, ge=1)
    question: str = Field(..., min_length=1)
    auto_run: bool = False
    auto_train_on_success: bool = False
    top_k_sql: int | None = Field(default=None, ge=1, le=50)
    top_k_schema: int | None = Field(default=None, ge=1, le=50)
    top_k_doc: int | None = Field(default=None, ge=1, le=50)


class QueryRequest(BaseModel):
    """统一 query 请求。"""

    datasource_id: int = Field(..., ge=1)
    kb_id: int | None = Field(default=None, ge=1)
    task_id: int | None = Field(default=None, ge=1)
    question: str = Field(..., min_length=1)
    explicit_params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    auto_run: bool = False
    auto_train_on_success: bool = False
    auto_infer: bool = True
    top_k_assets: int = Field(default=5, ge=1, le=20)
    asset_match_min_score: float | None = Field(default=None, ge=0.0, le=10.0)
    asset_match_min_margin: float | None = Field(default=None, ge=0.0, le=10.0)
    top_k_sql: int | None = Field(default=None, ge=1, le=50)
    top_k_schema: int | None = Field(default=None, ge=1, le=50)
    top_k_doc: int | None = Field(default=None, ge=1, le=50)


class PromoteSqlAssetRequest(BaseModel):
    asset_code: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    intent_summary: str | None = None
    asset_kind: str = Field(default="query", max_length=32)
    match_keywords: list[str] = Field(default_factory=list)
    match_examples: list[str] = Field(default_factory=list)
    parameter_schema_json: list[dict[str, Any]] = Field(default_factory=list)
    render_config_json: dict[str, Any] = Field(default_factory=dict)
    version_label: str | None = Field(default=None, max_length=64)


def _serialize_kb(row: VannaKnowledgeBase) -> dict[str, Any]:
    return row.to_dict()


def _serialize_schema_table(row: VannaSchemaTable) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "datasource_id": int(row.datasource_id),
        "harvest_job_id": int(row.harvest_job_id),
        "system_short": row.system_short,
        "env": row.env,
        "catalog_name": row.catalog_name,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "table_type": row.table_type,
        "table_comment": row.table_comment,
        "table_ddl": row.table_ddl,
        "primary_key_json": list(row.primary_key_json or []),
        "foreign_keys_json": list(row.foreign_keys_json or []),
        "indexes_json": list(row.indexes_json or []),
        "constraints_json": list(row.constraints_json or []),
        "row_count_estimate": row.row_count_estimate,
        "content_hash": row.content_hash,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_harvest_job(row: VannaSchemaHarvestJob) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "datasource_id": int(row.datasource_id),
        "system_short": row.system_short,
        "env": row.env,
        "status": row.status,
        "harvest_scope": row.harvest_scope,
        "schema_names_json": list(row.schema_names_json or []),
        "table_names_json": list(row.table_names_json or []),
        "request_payload_json": dict(row.request_payload_json or {}),
        "result_payload_json": dict(row.result_payload_json or {}),
        "error_message": row.error_message,
        "create_user_id": int(row.create_user_id),
        "create_user_name": row.create_user_name,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_schema_column(row: VannaSchemaColumn) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "table_id": int(row.table_id),
        "kb_id": int(row.kb_id),
        "datasource_id": int(row.datasource_id),
        "system_short": row.system_short,
        "env": row.env,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "column_name": row.column_name,
        "ordinal_position": row.ordinal_position,
        "data_type": row.data_type,
        "udt_name": row.udt_name,
        "is_nullable": row.is_nullable,
        "default_raw": row.default_raw,
        "default_kind": row.default_kind,
        "column_comment": row.column_comment,
        "is_primary_key": row.is_primary_key,
        "is_foreign_key": row.is_foreign_key,
        "foreign_table_name": row.foreign_table_name,
        "foreign_column_name": row.foreign_column_name,
        "is_generated": row.is_generated,
        "generation_expression": row.generation_expression,
        "value_source_kind": row.value_source_kind,
        "allowed_values_json": list(row.allowed_values_json or []),
        "sample_values_json": list(row.sample_values_json or []),
        "stats_json": dict(row.stats_json or {}),
        "semantic_tags_json": list(row.semantic_tags_json or []),
        "content_hash": row.content_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_entry(row: VannaTrainingEntry) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "datasource_id": int(row.datasource_id),
        "system_short": row.system_short,
        "env": row.env,
        "entry_code": row.entry_code,
        "entry_type": row.entry_type,
        "source_kind": row.source_kind,
        "source_ref": row.source_ref,
        "lifecycle_status": row.lifecycle_status,
        "quality_status": row.quality_status,
        "title": row.title,
        "question_text": row.question_text,
        "sql_text": row.sql_text,
        "sql_explanation": row.sql_explanation,
        "doc_text": row.doc_text,
        "schema_name": row.schema_name,
        "table_name": row.table_name,
        "business_domain": row.business_domain,
        "system_name": row.system_name,
        "subject_area": row.subject_area,
        "statement_kind": row.statement_kind,
        "tables_read_json": list(row.tables_read_json or []),
        "columns_read_json": list(row.columns_read_json or []),
        "output_fields_json": list(row.output_fields_json or []),
        "variables_json": list(row.variables_json or []),
        "tags_json": list(row.tags_json or []),
        "verification_result_json": dict(row.verification_result_json or {}),
        "quality_score": row.quality_score,
        "content_hash": row.content_hash,
        "create_user_id": int(row.create_user_id),
        "create_user_name": row.create_user_name,
        "verified_by": row.verified_by,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_ask_run(row: VannaAskRun) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "datasource_id": int(row.datasource_id),
        "system_short": row.system_short,
        "env": row.env,
        "task_id": row.task_id,
        "question_text": row.question_text,
        "rewritten_question": row.rewritten_question,
        "retrieval_snapshot_json": dict(row.retrieval_snapshot_json or {}),
        "prompt_snapshot_json": dict(row.prompt_snapshot_json or {}),
        "generated_sql": row.generated_sql,
        "sql_confidence": row.sql_confidence,
        "execution_mode": row.execution_mode,
        "execution_status": row.execution_status,
        "execution_result_json": dict(row.execution_result_json or {}),
        "approval_status": row.approval_status,
        "auto_train_entry_id": row.auto_train_entry_id,
        "create_user_id": int(row.create_user_id),
        "create_user_name": row.create_user_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get_owned_entry_or_404(
    *,
    db: Session,
    user_id: int,
    entry_id: int,
) -> VannaTrainingEntry:
    entry = (
        db.query(VannaTrainingEntry)
        .join(VannaKnowledgeBase, VannaTrainingEntry.kb_id == VannaKnowledgeBase.id)
        .filter(
            VannaTrainingEntry.id == int(entry_id),
            VannaKnowledgeBase.owner_user_id == int(user_id),
        )
        .first()
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training entry not found",
        )
    return entry


def _sync_entry_chunks(
    *,
    db: Session,
    entry: VannaTrainingEntry,
) -> None:
    chunk_rows = (
        db.query(VannaEmbeddingChunk)
        .filter(VannaEmbeddingChunk.entry_id == int(entry.id))
        .all()
    )
    if chunk_rows:
        for chunk_row in chunk_rows:
            chunk_row.lifecycle_status = entry.lifecycle_status
        db.commit()
        return

    IndexService(db).reindex_entry(entry_id=int(entry.id))


@vanna_router.post("/kbs")
async def create_or_update_kb(
    payload: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """创建或更新当前数据源默认知识库。"""
    service = KnowledgeBaseService(db)
    kb = service.get_or_create_default_kb(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        owner_user_name=getattr(user, "username", None),
    )
    if payload.name:
        kb.name = payload.name.strip()
    if payload.description is not None:
        kb.description = payload.description
    if payload.default_top_k_sql is not None:
        kb.default_top_k_sql = int(payload.default_top_k_sql)
    if payload.default_top_k_schema is not None:
        kb.default_top_k_schema = int(payload.default_top_k_schema)
    if payload.default_top_k_doc is not None:
        kb.default_top_k_doc = int(payload.default_top_k_doc)
    if payload.embedding_model is not None:
        kb.embedding_model = payload.embedding_model.strip() or None
    if payload.llm_model is not None:
        kb.llm_model = payload.llm_model.strip() or None
    db.commit()
    db.refresh(kb)
    return {"data": _serialize_kb(kb)}


@vanna_router.get("/kbs")
async def list_kbs(
    datasource_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出当前用户知识库。"""
    rows = KnowledgeBaseService(db).list_kbs(
        owner_user_id=int(user.id),
        datasource_id=int(datasource_id) if datasource_id is not None else None,
    )
    return {"data": [_serialize_kb(row) for row in rows]}


@vanna_router.get("/kbs/{kb_id}")
async def get_kb_detail(
    kb_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """读取知识库详情。"""
    kb = KnowledgeBaseService(db).get_kb(kb_id=int(kb_id), owner_user_id=int(user.id))
    return {"data": _serialize_kb(kb)}


@vanna_router.post("/schema-harvest/preview")
async def preview_schema_harvest(
    payload: SchemaHarvestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """预览 schema 采集范围。"""
    result = await SchemaHarvestService(db).preview_harvest(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        schema_names=list(payload.schema_names or []),
        table_names=list(payload.table_names or []),
    )
    return {"data": asdict(result)}


@vanna_router.post("/schema-harvest/commit")
async def commit_schema_harvest(
    payload: SchemaHarvestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """提交 schema 采集。"""
    result = await SchemaHarvestService(db).commit_harvest(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        owner_user_name=getattr(user, "username", None),
        schema_names=list(payload.schema_names or []),
        table_names=list(payload.table_names or []),
    )
    return {"data": asdict(result)}


@vanna_router.get("/schema-tables")
async def list_schema_tables(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    schema_name: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出结构事实表。"""
    query = (
        db.query(VannaSchemaTable)
        .join(VannaKnowledgeBase, VannaSchemaTable.kb_id == VannaKnowledgeBase.id)
        .filter(VannaKnowledgeBase.owner_user_id == int(user.id))
    )
    if kb_id is not None:
        query = query.filter(VannaSchemaTable.kb_id == int(kb_id))
    if datasource_id is not None:
        query = query.filter(VannaSchemaTable.datasource_id == int(datasource_id))
    if status_filter:
        query = query.filter(VannaSchemaTable.status == status_filter)
    if schema_name:
        query = query.filter(VannaSchemaTable.schema_name == schema_name)
    if table_name:
        query = query.filter(VannaSchemaTable.table_name == table_name)

    rows = query.order_by(
        VannaSchemaTable.updated_at.desc(),
        VannaSchemaTable.id.desc(),
    ).all()
    return {"data": [_serialize_schema_table(row) for row in rows]}


@vanna_router.get("/harvest-jobs")
async def list_harvest_jobs(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出 schema 采集任务。"""
    query = (
        db.query(VannaSchemaHarvestJob)
        .join(VannaKnowledgeBase, VannaSchemaHarvestJob.kb_id == VannaKnowledgeBase.id)
        .filter(VannaKnowledgeBase.owner_user_id == int(user.id))
    )
    if kb_id is not None:
        query = query.filter(VannaSchemaHarvestJob.kb_id == int(kb_id))
    if datasource_id is not None:
        query = query.filter(VannaSchemaHarvestJob.datasource_id == int(datasource_id))
    if status_filter:
        query = query.filter(VannaSchemaHarvestJob.status == status_filter)

    rows = query.order_by(
        VannaSchemaHarvestJob.created_at.desc(),
        VannaSchemaHarvestJob.id.desc(),
    ).all()
    return {"data": [_serialize_harvest_job(row) for row in rows]}


@vanna_router.get("/schema-columns")
async def list_schema_columns(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    schema_name: Optional[str] = Query(default=None),
    table_name: Optional[str] = Query(default=None),
    column_name: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出字段事实。"""
    query = (
        db.query(VannaSchemaColumn)
        .join(VannaKnowledgeBase, VannaSchemaColumn.kb_id == VannaKnowledgeBase.id)
        .filter(VannaKnowledgeBase.owner_user_id == int(user.id))
    )
    if kb_id is not None:
        query = query.filter(VannaSchemaColumn.kb_id == int(kb_id))
    if datasource_id is not None:
        query = query.filter(VannaSchemaColumn.datasource_id == int(datasource_id))
    if schema_name:
        query = query.filter(VannaSchemaColumn.schema_name == schema_name)
    if table_name:
        query = query.filter(VannaSchemaColumn.table_name == table_name)
    if column_name:
        query = query.filter(VannaSchemaColumn.column_name == column_name)

    rows = query.order_by(
        VannaSchemaColumn.table_name.asc(),
        VannaSchemaColumn.ordinal_position.asc(),
        VannaSchemaColumn.id.asc(),
    ).all()
    return {"data": [_serialize_schema_column(row) for row in rows]}


@vanna_router.post("/train")
async def train_vanna_entry(
    payload: TrainRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """手工训练 question_sql/documentation，或 bootstrap schema。"""
    service = TrainService(db)
    index_service = IndexService(db)

    if payload.bootstrap_schema:
        entries = service.bootstrap_schema(
            datasource_id=int(payload.datasource_id),
            owner_user_id=int(user.id),
            create_user_name=getattr(user, "username", None),
        )
        for entry in entries:
            index_service.reindex_entry(entry_id=int(entry.id))
        return {"data": [_serialize_entry(entry) for entry in entries]}

    if payload.question and payload.sql:
        entry = service.train_question_sql(
            datasource_id=int(payload.datasource_id),
            owner_user_id=int(user.id),
            create_user_name=getattr(user, "username", None),
            question=payload.question,
            sql=payload.sql,
            publish=bool(payload.publish),
        )
        index_service.reindex_entry(entry_id=int(entry.id))
        return {"data": _serialize_entry(entry)}

    if payload.documentation:
        if not payload.title or not payload.title.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="title is required when documentation is provided",
            )
        entry = service.train_documentation(
            datasource_id=int(payload.datasource_id),
            owner_user_id=int(user.id),
            create_user_name=getattr(user, "username", None),
            title=payload.title,
            documentation=payload.documentation,
            publish=bool(payload.publish),
        )
        index_service.reindex_entry(entry_id=int(entry.id))
        return {"data": _serialize_entry(entry)}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Either bootstrap_schema or (question + sql) or documentation must be provided",
    )


@vanna_router.get("/entries")
async def list_training_entries(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    entry_type: Optional[str] = Query(default=None),
    lifecycle_status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出训练条目。"""
    query = (
        db.query(VannaTrainingEntry)
        .join(VannaKnowledgeBase, VannaTrainingEntry.kb_id == VannaKnowledgeBase.id)
        .filter(VannaKnowledgeBase.owner_user_id == int(user.id))
    )
    if kb_id is not None:
        query = query.filter(VannaTrainingEntry.kb_id == int(kb_id))
    if datasource_id is not None:
        query = query.filter(VannaTrainingEntry.datasource_id == int(datasource_id))
    if entry_type:
        query = query.filter(VannaTrainingEntry.entry_type == entry_type)
    if lifecycle_status:
        query = query.filter(VannaTrainingEntry.lifecycle_status == lifecycle_status)

    rows = query.order_by(
        VannaTrainingEntry.updated_at.desc(),
        VannaTrainingEntry.id.desc(),
    ).all()
    return {"data": [_serialize_entry(row) for row in rows]}


@vanna_router.post("/entries/{entry_id}/publish")
async def publish_training_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """发布候选条目。"""
    entry = _get_owned_entry_or_404(db=db, user_id=int(user.id), entry_id=int(entry_id))
    entry.lifecycle_status = "published"
    _sync_entry_chunks(db=db, entry=entry)
    db.refresh(entry)
    return {"data": _serialize_entry(entry)}


@vanna_router.post("/entries/{entry_id}/archive")
async def archive_training_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """归档训练条目。"""
    entry = _get_owned_entry_or_404(db=db, user_id=int(user.id), entry_id=int(entry_id))
    entry.lifecycle_status = "archived"
    _sync_entry_chunks(db=db, entry=entry)
    db.refresh(entry)
    return {"data": _serialize_entry(entry)}


@vanna_router.post("/ask")
async def ask_vanna_sql(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """执行 Vanna ask。"""
    result = await AskService(db).ask(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        create_user_name=getattr(user, "username", None),
        question=payload.question,
        kb_id=payload.kb_id,
        task_id=payload.task_id,
        top_k_sql=payload.top_k_sql,
        top_k_schema=payload.top_k_schema,
        top_k_doc=payload.top_k_doc,
        auto_run=bool(payload.auto_run),
        auto_train_on_success=bool(payload.auto_train_on_success),
    )
    return {
        "data": {
            "ask_run_id": int(result.ask_run_id),
            "execution_status": result.execution_status,
            "generated_sql": result.generated_sql,
            "sql_confidence": result.sql_confidence,
            "execution_result": result.execution_result,
            "auto_train_entry_id": result.auto_train_entry_id,
        }
    }


def _serialize_asset(row: VannaSqlAsset) -> dict[str, Any]:
    return row.to_dict()


def _serialize_asset_version(row: VannaSqlAssetVersion) -> dict[str, Any]:
    return row.to_dict()


def _raise_vanna_bad_request(message: str) -> None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _raise_from_value_error(message: str) -> None:
    if "was not found" in message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    _raise_vanna_bad_request(message)


@vanna_router.post("/query")
async def query_vanna_sql(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """统一 query：先 asset-first，未命中再 ask-fallback。"""
    result = await QueryService(db).query(
        datasource_id=int(payload.datasource_id),
        owner_user_id=int(user.id),
        create_user_name=getattr(user, "username", None),
        question=payload.question,
        kb_id=payload.kb_id,
        task_id=payload.task_id,
        explicit_params=dict(payload.explicit_params or {}),
        context=dict(payload.context or {}),
        auto_run=bool(payload.auto_run),
        auto_train_on_success=bool(payload.auto_train_on_success),
        auto_infer=bool(payload.auto_infer),
        top_k_assets=int(payload.top_k_assets),
        asset_match_min_score=payload.asset_match_min_score,
        asset_match_min_margin=payload.asset_match_min_margin,
        top_k_sql=payload.top_k_sql,
        top_k_schema=payload.top_k_schema,
        top_k_doc=payload.top_k_doc,
    )
    return {"data": asdict(result)}


@vanna_router.get("/ask-runs")
async def list_ask_runs(
    kb_id: Optional[int] = Query(default=None),
    datasource_id: Optional[int] = Query(default=None),
    execution_status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """列出 ask 运行记录。"""
    query = (
        db.query(VannaAskRun)
        .join(VannaKnowledgeBase, VannaAskRun.kb_id == VannaKnowledgeBase.id)
        .filter(VannaKnowledgeBase.owner_user_id == int(user.id))
    )
    if kb_id is not None:
        query = query.filter(VannaAskRun.kb_id == int(kb_id))
    if datasource_id is not None:
        query = query.filter(VannaAskRun.datasource_id == int(datasource_id))
    if execution_status:
        query = query.filter(VannaAskRun.execution_status == execution_status)

    rows = query.order_by(VannaAskRun.created_at.desc(), VannaAskRun.id.desc()).all()
    return {"data": [_serialize_ask_run(row) for row in rows]}


@vanna_router.post("/ask-runs/{ask_run_id}/promote")
async def promote_ask_run_to_asset(
    ask_run_id: int,
    payload: PromoteSqlAssetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset, version = SqlAssetService(db).promote_ask_run(
            ask_run_id=int(ask_run_id),
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
            parameter_schema_json=list(payload.parameter_schema_json or []),
            render_config_json=dict(payload.render_config_json or {}),
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {
        "data": {
            "asset": _serialize_asset(asset),
            "version": _serialize_asset_version(version),
        }
    }


@vanna_router.post("/entries/{entry_id}/promote")
async def promote_training_entry_to_asset(
    entry_id: int,
    payload: PromoteSqlAssetRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        asset, version = SqlAssetService(db).promote_training_entry(
            entry_id=int(entry_id),
            owner_user_id=int(user.id),
            owner_user_name=getattr(user, "username", None),
            asset_code=payload.asset_code,
            name=payload.name,
            description=payload.description,
            intent_summary=payload.intent_summary,
            asset_kind=payload.asset_kind,
            match_keywords=list(payload.match_keywords or []),
            match_examples=list(payload.match_examples or []),
            parameter_schema_json=list(payload.parameter_schema_json or []),
            render_config_json=dict(payload.render_config_json or {}),
            version_label=payload.version_label,
        )
    except ValueError as exc:
        _raise_from_value_error(str(exc))
    return {
        "data": {
            "asset": _serialize_asset(asset),
            "version": _serialize_asset_version(version),
        }
    }
