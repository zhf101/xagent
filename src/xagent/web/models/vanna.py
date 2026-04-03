"""Vanna SQL 资产宿主模型。

这一组模型服务的是独立的 `xagent.vanna` 模块：
- 结构事实层：schema/table/column 的保真快照
- 训练知识层：question_sql、schema_summary、documentation
- 检索切片层：pgvector chunk 与 ask 运行记录

当前文件只定义持久化边界，不承载服务层逻辑。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict

from sqlalchemy import JSON, Boolean, Column
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import func
from sqlalchemy.types import UserDefinedType

from .database import Base

# mypy: ignore-errors


class VectorColumn(UserDefinedType):
    """兼容 SQLite 测试与 PostgreSQL pgvector 的向量列类型。

    - PostgreSQL: 编译成 `vector(dim)`
    - SQLite: 回退成 `TEXT`，仅用于模型测试和迁移校验
    """

    cache_ok = True

    def __init__(self, dimensions: int):
        self.dimensions = int(dimensions)

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dimensions})"


@compiles(VectorColumn, "sqlite")
def _compile_vector_sqlite(type_: VectorColumn, compiler, **kw) -> str:
    del type_, compiler, kw
    return "TEXT"


@compiles(VectorColumn, "postgresql")
def _compile_vector_postgresql(type_: VectorColumn, compiler, **kw) -> str:
    del compiler, kw
    return f"vector({type_.dimensions})"


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


class VannaKnowledgeBaseStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class VannaHarvestJobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VannaSchemaTableStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


class VannaTrainingLifecycleStatus(str, Enum):
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class VannaTrainingQualityStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class VannaAskExecutionStatus(str, Enum):
    GENERATED = "generated"
    EXECUTED = "executed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class VannaKnowledgeBase(Base):
    """Vanna 知识库宿主。"""

    __tablename__ = "vanna_knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    kb_code = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    owner_user_id = Column(Integer, nullable=False, index=True)
    owner_user_name = Column(String(255), nullable=True)
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    datasource_name = Column(String(255), nullable=True)
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    db_type = Column(String(64), nullable=True, index=True)
    dialect = Column(String(64), nullable=True, index=True)
    status = Column(
        String(32),
        nullable=False,
        default=VannaKnowledgeBaseStatus.DRAFT.value,
        index=True,
    )
    default_top_k_sql = Column(Integer, nullable=True)
    default_top_k_schema = Column(Integer, nullable=True)
    default_top_k_doc = Column(Integer, nullable=True)
    embedding_model = Column(String(128), nullable=True)
    llm_model = Column(String(128), nullable=True)
    last_train_at = Column(DateTime, nullable=True)
    last_ask_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kb_code": self.kb_code,
            "name": self.name,
            "description": self.description,
            "owner_user_id": self.owner_user_id,
            "owner_user_name": self.owner_user_name,
            "datasource_id": self.datasource_id,
            "datasource_name": self.datasource_name,
            "system_short": self.system_short,
            "env": self.env,
            "db_type": self.db_type,
            "dialect": self.dialect,
            "status": self.status,
            "default_top_k_sql": self.default_top_k_sql,
            "default_top_k_schema": self.default_top_k_schema,
            "default_top_k_doc": self.default_top_k_doc,
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "last_train_at": _isoformat(self.last_train_at),
            "last_ask_at": _isoformat(self.last_ask_at),
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }


class VannaSchemaHarvestJob(Base):
    """Schema 采集任务。"""

    __tablename__ = "vanna_schema_harvest_jobs"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    status = Column(
        String(32),
        nullable=False,
        default=VannaHarvestJobStatus.RUNNING.value,
        index=True,
    )
    harvest_scope = Column(String(32), nullable=False, default="all")
    schema_names_json = Column(JSON, nullable=True, default=list)
    table_names_json = Column(JSON, nullable=True, default=list)
    request_payload_json = Column(JSON, nullable=True, default=dict)
    result_payload_json = Column(JSON, nullable=True, default=dict)
    error_message = Column(Text, nullable=True)
    create_user_id = Column(Integer, nullable=False, index=True)
    create_user_name = Column(String(255), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class VannaSchemaTable(Base):
    """表级结构事实。"""

    __tablename__ = "vanna_schema_tables"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    harvest_job_id = Column(
        Integer,
        ForeignKey("vanna_schema_harvest_jobs.id"),
        nullable=False,
        index=True,
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    catalog_name = Column(String(255), nullable=True)
    schema_name = Column(String(255), nullable=True, index=True)
    table_name = Column(String(255), nullable=False, index=True)
    table_type = Column(String(64), nullable=True)
    table_comment = Column(Text, nullable=True)
    table_ddl = Column(Text, nullable=True)
    primary_key_json = Column(JSON, nullable=True, default=list)
    foreign_keys_json = Column(JSON, nullable=True, default=list)
    indexes_json = Column(JSON, nullable=True, default=list)
    constraints_json = Column(JSON, nullable=True, default=list)
    row_count_estimate = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    status = Column(
        String(32),
        nullable=False,
        default=VannaSchemaTableStatus.ACTIVE.value,
        index=True,
    )
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class VannaSchemaColumn(Base):
    """字段级结构事实。"""

    __tablename__ = "vanna_schema_columns"

    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(
        Integer, ForeignKey("vanna_schema_tables.id"), nullable=False, index=True
    )
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    schema_name = Column(String(255), nullable=True, index=True)
    table_name = Column(String(255), nullable=False, index=True)
    column_name = Column(String(255), nullable=False, index=True)
    ordinal_position = Column(Integer, nullable=True)
    data_type = Column(String(128), nullable=True)
    udt_name = Column(String(128), nullable=True)
    is_nullable = Column(Boolean, nullable=True)
    default_raw = Column(Text, nullable=True)
    default_kind = Column(String(32), nullable=True, index=True)
    column_comment = Column(Text, nullable=True)
    is_primary_key = Column(Boolean, nullable=True)
    is_foreign_key = Column(Boolean, nullable=True)
    foreign_table_name = Column(String(255), nullable=True)
    foreign_column_name = Column(String(255), nullable=True)
    is_generated = Column(Boolean, nullable=True)
    generation_expression = Column(Text, nullable=True)
    value_source_kind = Column(String(32), nullable=True, index=True)
    allowed_values_json = Column(JSON, nullable=True, default=list)
    sample_values_json = Column(JSON, nullable=True, default=list)
    stats_json = Column(JSON, nullable=True, default=dict)
    semantic_tags_json = Column(JSON, nullable=True, default=list)
    content_hash = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class VannaTrainingEntry(Base):
    """训练知识条目。"""

    __tablename__ = "vanna_training_entries"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    entry_code = Column(String(255), unique=True, index=True, nullable=False)
    entry_type = Column(String(32), nullable=False, index=True)
    source_kind = Column(String(32), nullable=True, index=True)
    source_ref = Column(String(255), nullable=True)
    lifecycle_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingLifecycleStatus.CANDIDATE.value,
        index=True,
    )
    quality_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingQualityStatus.UNVERIFIED.value,
        index=True,
    )
    title = Column(String(255), nullable=True)
    question_text = Column(Text, nullable=True)
    sql_text = Column(Text, nullable=True)
    sql_explanation = Column(Text, nullable=True)
    doc_text = Column(Text, nullable=True)
    schema_name = Column(String(255), nullable=True, index=True)
    table_name = Column(String(255), nullable=True, index=True)
    business_domain = Column(String(128), nullable=True, index=True)
    system_name = Column(String(128), nullable=True, index=True)
    subject_area = Column(String(128), nullable=True, index=True)
    statement_kind = Column(String(32), nullable=True, index=True)
    tables_read_json = Column(JSON, nullable=True, default=list)
    columns_read_json = Column(JSON, nullable=True, default=list)
    output_fields_json = Column(JSON, nullable=True, default=list)
    variables_json = Column(JSON, nullable=True, default=list)
    tags_json = Column(JSON, nullable=True, default=list)
    verification_result_json = Column(JSON, nullable=True, default=dict)
    quality_score = Column(Float, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)
    create_user_id = Column(Integer, nullable=False, index=True)
    create_user_name = Column(String(255), nullable=True)
    verified_by = Column(String(255), nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )


class VannaEmbeddingChunk(Base):
    """训练知识切片。"""

    __tablename__ = "vanna_embedding_chunks"
    __table_args__ = (
        Index(
            "ix_vanna_embedding_chunks_kb_chunk_lifecycle_model",
            "kb_id",
            "chunk_type",
            "lifecycle_status",
            "embedding_model",
        ),
        Index(
            "ix_vanna_embedding_chunks_entry_chunk_type",
            "entry_id",
            "chunk_type",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    entry_id = Column(
        Integer, ForeignKey("vanna_training_entries.id"), nullable=False, index=True
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    source_table = Column(String(64), nullable=True, index=True)
    source_row_id = Column(Integer, nullable=True, index=True)
    chunk_type = Column(String(32), nullable=False, index=True)
    chunk_order = Column(Integer, nullable=False, default=0)
    chunk_text = Column(Text, nullable=False)
    embedding_text = Column(Text, nullable=True)
    embedding_model = Column(String(128), nullable=True, index=True)
    embedding_dim = Column(Integer, nullable=True)
    embedding_vector = Column(VectorColumn(1536), nullable=True)
    distance_metric = Column(String(16), nullable=True)
    token_count_estimate = Column(Integer, nullable=True)
    lifecycle_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingLifecycleStatus.CANDIDATE.value,
        index=True,
    )
    metadata_json = Column(JSON, nullable=True, default=dict)
    chunk_hash = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class VannaAskRun(Base):
    """Ask 调用运行事实。"""

    __tablename__ = "vanna_ask_runs"

    id = Column(Integer, primary_key=True, index=True)
    kb_id = Column(
        Integer, ForeignKey("vanna_knowledge_bases.id"), nullable=False, index=True
    )
    datasource_id = Column(
        Integer, ForeignKey("text2sql_databases.id"), nullable=False, index=True
    )
    system_short = Column(String(64), nullable=False, index=True)
    env = Column(String(32), nullable=False, index=True)
    task_id = Column(Integer, nullable=True, index=True)
    question_text = Column(Text, nullable=False)
    rewritten_question = Column(Text, nullable=True)
    retrieval_snapshot_json = Column(JSON, nullable=True, default=dict)
    prompt_snapshot_json = Column(JSON, nullable=True, default=dict)
    generated_sql = Column(Text, nullable=True)
    sql_confidence = Column(Float, nullable=True)
    execution_mode = Column(String(32), nullable=True, index=True)
    execution_status = Column(
        String(32),
        nullable=False,
        default=VannaAskExecutionStatus.GENERATED.value,
        index=True,
    )
    execution_result_json = Column(JSON, nullable=True, default=dict)
    approval_status = Column(String(32), nullable=True, index=True)
    auto_train_entry_id = Column(
        Integer, ForeignKey("vanna_training_entries.id"), nullable=True, index=True
    )
    create_user_id = Column(Integer, nullable=False, index=True)
    create_user_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
