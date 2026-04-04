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

    id = Column(Integer, primary_key=True, index=True, comment="知识库ID")
    kb_code = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="知识库唯一编码",
    )
    name = Column(String(255), nullable=False, comment="知识库名称")
    description = Column(Text, nullable=True, comment="知识库描述")
    owner_user_id = Column(
        Integer, nullable=False, index=True, comment="所有者用户ID"
    )
    owner_user_name = Column(
        String(255), nullable=True, comment="所有者用户名"
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="关联的数据源ID",
    )
    datasource_name = Column(
        String(255), nullable=True, comment="数据源名称"
    )
    system_short = Column(
        String(64),
        nullable=False,
        index=True,
        comment="系统简称",
    )
    env = Column(
        String(32),
        nullable=False,
        index=True,
        comment="环境（如prod/dev）",
    )
    db_type = Column(
        String(64), nullable=True, index=True, comment="数据库类型"
    )
    dialect = Column(
        String(64), nullable=True, index=True, comment="SQL方言"
    )
    status = Column(
        String(32),
        nullable=False,
        default=VannaKnowledgeBaseStatus.DRAFT.value,
        index=True,
        comment="知识库状态（draft/active/archived）",
    )
    default_top_k_sql = Column(
        Integer, nullable=True, comment="默认SQL检索TopK"
    )
    default_top_k_schema = Column(
        Integer, nullable=True, comment="默认Schema检索TopK"
    )
    default_top_k_doc = Column(
        Integer, nullable=True, comment="默认文档检索TopK"
    )
    embedding_model = Column(
        String(128), nullable=True, comment="嵌入模型名称"
    )
    llm_model = Column(
        String(128), nullable=True, comment="LLM模型名称"
    )
    last_train_at = Column(
        DateTime, nullable=True, comment="最后训练时间"
    )
    last_ask_at = Column(
        DateTime, nullable=True, comment="最后查询时间"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
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

    id = Column(Integer, primary_key=True, index=True, comment="采集任务ID")
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    status = Column(
        String(32),
        nullable=False,
        default=VannaHarvestJobStatus.RUNNING.value,
        index=True,
        comment="任务状态（running/completed/failed）",
    )
    harvest_scope = Column(
        String(32),
        nullable=False,
        default="all",
        comment="采集范围（all/custom）",
    )
    schema_names_json = Column(
        JSON, nullable=True, default=list, comment="Schema名称列表（JSON格式）"
    )
    table_names_json = Column(
        JSON, nullable=True, default=list, comment="表名称列表（JSON格式）"
    )
    request_payload_json = Column(
        JSON, nullable=True, default=dict, comment="请求参数（JSON格式）"
    )
    result_payload_json = Column(
        JSON, nullable=True, default=dict, comment="采集结果（JSON格式）"
    )
    error_message = Column(Text, nullable=True, comment="错误信息")
    create_user_id = Column(
        Integer, nullable=False, index=True, comment="创建用户ID"
    )
    create_user_name = Column(
        String(255), nullable=True, comment="创建用户名"
    )
    started_at = Column(
        DateTime, nullable=True, comment="开始时间"
    )
    completed_at = Column(
        DateTime, nullable=True, comment="完成时间"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class VannaSchemaTable(Base):
    """表级结构事实。"""

    __tablename__ = "vanna_schema_tables"

    id = Column(Integer, primary_key=True, index=True, comment="表结构ID")
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    harvest_job_id = Column(
        Integer,
        ForeignKey("vanna_schema_harvest_jobs.id"),
        nullable=False,
        index=True,
        comment="采集任务ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    catalog_name = Column(
        String(255), nullable=True, comment="目录名称"
    )
    schema_name = Column(
        String(255), nullable=True, index=True, comment="Schema名称"
    )
    table_name = Column(
        String(255), nullable=False, index=True, comment="表名称"
    )
    table_type = Column(
        String(64), nullable=True, comment="表类型（如table/view）"
    )
    table_comment = Column(Text, nullable=True, comment="表注释")
    table_ddl = Column(Text, nullable=True, comment="表DDL语句")
    primary_key_json = Column(
        JSON, nullable=True, default=list, comment="主键信息（JSON格式）"
    )
    foreign_keys_json = Column(
        JSON, nullable=True, default=list, comment="外键信息（JSON格式）"
    )
    indexes_json = Column(
        JSON, nullable=True, default=list, comment="索引信息（JSON格式）"
    )
    constraints_json = Column(
        JSON, nullable=True, default=list, comment="约束信息（JSON格式）"
    )
    row_count_estimate = Column(
        Integer, nullable=True, comment="行数估计"
    )
    content_hash = Column(
        String(64), nullable=True, index=True, comment="内容哈希"
    )
    status = Column(
        String(32),
        nullable=False,
        default=VannaSchemaTableStatus.ACTIVE.value,
        index=True,
        comment="表状态（active/stale/archived）",
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class VannaSchemaColumn(Base):
    """字段级结构事实。"""

    __tablename__ = "vanna_schema_columns"

    id = Column(Integer, primary_key=True, index=True, comment="字段结构ID")
    table_id = Column(
        Integer,
        ForeignKey("vanna_schema_tables.id"),
        nullable=False,
        index=True,
        comment="表结构ID",
    )
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    schema_name = Column(
        String(255), nullable=True, index=True, comment="Schema名称"
    )
    table_name = Column(
        String(255), nullable=False, index=True, comment="表名称"
    )
    column_name = Column(
        String(255), nullable=False, index=True, comment="字段名称"
    )
    ordinal_position = Column(
        Integer, nullable=True, comment="字段位置"
    )
    data_type = Column(
        String(128), nullable=True, comment="数据类型"
    )
    udt_name = Column(
        String(128), nullable=True, comment="用户定义类型名称"
    )
    is_nullable = Column(
        Boolean, nullable=True, comment="是否可空"
    )
    default_raw = Column(
        Text, nullable=True, comment="默认值（原始）"
    )
    default_kind = Column(
        String(32), nullable=True, index=True, comment="默认值类型"
    )
    column_comment = Column(Text, nullable=True, comment="字段注释")
    is_primary_key = Column(
        Boolean, nullable=True, comment="是否主键"
    )
    is_foreign_key = Column(
        Boolean, nullable=True, comment="是否外键"
    )
    foreign_table_name = Column(
        String(255), nullable=True, comment="外键表名称"
    )
    foreign_column_name = Column(
        String(255), nullable=True, comment="外键字段名称"
    )
    is_generated = Column(
        Boolean, nullable=True, comment="是否生成列"
    )
    generation_expression = Column(
        Text, nullable=True, comment="生成表达式"
    )
    value_source_kind = Column(
        String(32), nullable=True, index=True, comment="值来源类型"
    )
    allowed_values_json = Column(
        JSON, nullable=True, default=list, comment="允许值列表（JSON格式）"
    )
    sample_values_json = Column(
        JSON, nullable=True, default=list, comment="示例值列表（JSON格式）"
    )
    stats_json = Column(
        JSON, nullable=True, default=dict, comment="统计信息（JSON格式）"
    )
    semantic_tags_json = Column(
        JSON, nullable=True, default=list, comment="语义标签（JSON格式）"
    )
    content_hash = Column(
        String(64), nullable=True, index=True, comment="内容哈希"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class VannaTrainingEntry(Base):
    """训练知识条目。"""

    __tablename__ = "vanna_training_entries"

    id = Column(Integer, primary_key=True, index=True, comment="训练条目ID")
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    entry_code = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="训练条目唯一编码",
    )
    entry_type = Column(
        String(32),
        nullable=False,
        index=True,
        comment="条目类型（question_sql/schema_summary/documentation）",
    )
    source_kind = Column(
        String(32),
        nullable=True,
        index=True,
        comment="来源类型（manual/auto_import/harvest）",
    )
    source_ref = Column(
        String(255), nullable=True, comment="来源引用"
    )
    lifecycle_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingLifecycleStatus.CANDIDATE.value,
        index=True,
        comment="生命周期状态（candidate/published/archived）",
    )
    quality_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingQualityStatus.UNVERIFIED.value,
        index=True,
        comment="质量状态（unverified/verified/rejected）",
    )
    title = Column(
        String(255), nullable=True, comment="标题"
    )
    question_text = Column(
        Text, nullable=True, comment="问题文本"
    )
    sql_text = Column(Text, nullable=True, comment="SQL语句")
    sql_explanation = Column(Text, nullable=True, comment="SQL解释")
    doc_text = Column(Text, nullable=True, comment="文档文本")
    schema_name = Column(
        String(255), nullable=True, index=True, comment="Schema名称"
    )
    table_name = Column(
        String(255), nullable=True, index=True, comment="表名称"
    )
    business_domain = Column(
        String(128), nullable=True, index=True, comment="业务域"
    )
    system_name = Column(
        String(128), nullable=True, index=True, comment="系统名称"
    )
    subject_area = Column(
        String(128), nullable=True, index=True, comment="主题域"
    )
    statement_kind = Column(
        String(32), nullable=True, index=True, comment="语句类型（SELECT/INSERT/UPDATE/DELETE）"
    )
    tables_read_json = Column(
        JSON, nullable=True, default=list, comment="读取的表列表（JSON格式）"
    )
    columns_read_json = Column(
        JSON, nullable=True, default=list, comment="读取的字段列表（JSON格式）"
    )
    output_fields_json = Column(
        JSON, nullable=True, default=list, comment="输出字段列表（JSON格式）"
    )
    variables_json = Column(
        JSON, nullable=True, default=list, comment="变量列表（JSON格式）"
    )
    tags_json = Column(
        JSON, nullable=True, default=list, comment="标签列表（JSON格式）"
    )
    verification_result_json = Column(
        JSON, nullable=True, default=dict, comment="验证结果（JSON格式）"
    )
    quality_score = Column(
        Float, nullable=True, comment="质量分数"
    )
    content_hash = Column(
        String(64), nullable=True, index=True, comment="内容哈希"
    )
    create_user_id = Column(
        Integer, nullable=False, index=True, comment="创建用户ID"
    )
    create_user_name = Column(
        String(255), nullable=True, comment="创建用户名"
    )
    verified_by = Column(
        String(255), nullable=True, comment="验证人"
    )
    verified_at = Column(
        DateTime, nullable=True, comment="验证时间"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
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

    id = Column(Integer, primary_key=True, index=True, comment="切片ID")
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    entry_id = Column(
        Integer,
        ForeignKey("vanna_training_entries.id"),
        nullable=False,
        index=True,
        comment="训练条目ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    source_table = Column(
        String(64), nullable=True, index=True, comment="来源表"
    )
    source_row_id = Column(
        Integer, nullable=True, index=True, comment="来源行ID"
    )
    chunk_type = Column(
        String(32),
        nullable=False,
        index=True,
        comment="切片类型（question_sql/schema_summary/documentation）",
    )
    chunk_order = Column(
        Integer, nullable=False, default=0, comment="切片顺序"
    )
    chunk_text = Column(Text, nullable=False, comment="切片文本")
    embedding_text = Column(Text, nullable=True, comment="嵌入文本")
    embedding_model = Column(
        String(128), nullable=True, index=True, comment="嵌入模型名称"
    )
    embedding_dim = Column(
        Integer, nullable=True, comment="嵌入维度"
    )
    embedding_vector = Column(
        VectorColumn(1536), nullable=True, comment="嵌入向量"
    )
    distance_metric = Column(
        String(16), nullable=True, comment="距离度量（如cosine/euclidean）"
    )
    token_count_estimate = Column(
        Integer, nullable=True, comment="Token数估计"
    )
    lifecycle_status = Column(
        String(32),
        nullable=False,
        default=VannaTrainingLifecycleStatus.CANDIDATE.value,
        index=True,
        comment="生命周期状态（candidate/published/archived）",
    )
    metadata_json = Column(
        JSON, nullable=True, default=dict, comment="元数据（JSON格式）"
    )
    chunk_hash = Column(
        String(64), nullable=True, index=True, comment="切片哈希"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )


class VannaAskRun(Base):
    """Ask 调用运行事实。"""

    __tablename__ = "vanna_ask_runs"

    id = Column(Integer, primary_key=True, index=True, comment="Ask运行ID")
    kb_id = Column(
        Integer,
        ForeignKey("vanna_knowledge_bases.id"),
        nullable=False,
        index=True,
        comment="知识库ID",
    )
    datasource_id = Column(
        Integer,
        ForeignKey("text2sql_databases.id"),
        nullable=False,
        index=True,
        comment="数据源ID",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境（如prod/dev）"
    )
    task_id = Column(
        Integer, nullable=True, index=True, comment="任务ID"
    )
    question_text = Column(Text, nullable=False, comment="问题文本")
    rewritten_question = Column(Text, nullable=True, comment="重写后的问题")
    retrieval_snapshot_json = Column(
        JSON, nullable=True, default=dict, comment="检索快照（JSON格式）"
    )
    prompt_snapshot_json = Column(
        JSON, nullable=True, default=dict, comment="提示快照（JSON格式）"
    )
    generated_sql = Column(Text, nullable=True, comment="生成的SQL")
    sql_confidence = Column(
        Float, nullable=True, comment="SQL置信度"
    )
    execution_mode = Column(
        String(32), nullable=True, index=True, comment="执行模式（dry_run/execute）"
    )
    execution_status = Column(
        String(32),
        nullable=False,
        default=VannaAskExecutionStatus.GENERATED.value,
        index=True,
        comment="执行状态（generated/executed/failed/waiting_approval）",
    )
    execution_result_json = Column(
        JSON, nullable=True, default=dict, comment="执行结果（JSON格式）"
    )
    approval_status = Column(
        String(32), nullable=True, index=True, comment="审批状态"
    )
    auto_train_entry_id = Column(
        Integer,
        ForeignKey("vanna_training_entries.id"),
        nullable=True,
        index=True,
        comment="自动训练条目ID",
    )
    create_user_id = Column(
        Integer, nullable=False, index=True, comment="创建用户ID"
    )
    create_user_name = Column(
        String(255), nullable=True, comment="创建用户名"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at = Column(
        DateTime,
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )