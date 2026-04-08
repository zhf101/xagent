"""SQL 资产宿主模型。

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
from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import func
from sqlalchemy.types import UserDefinedType

from xagent.web.models.database import Base

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
    """统一处理模型时间字段序列化。"""

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
    """Vanna 知识库宿主。

    这是 `gdp.vanna` 的一级聚合根，后续 schema、训练条目、ask run、SQL asset
    都会挂在它下面。审查这个模型时，重点看这些字段：

    - `datasource_id`: 这套知识到底绑定哪个数据源
    - `system_short / database_name / env`: 问答、资产、执行时的环境收缩条件
    - `default_top_k_*`: 检索默认策略，不同 kb 可以单独调参
    - `embedding_model / llm_model`: 记录当前知识库训练和问答依赖的模型名称
    """

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
    database_name = Column(
        String(255), nullable=True, index=True, comment="逻辑数据库名称"
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
        """输出知识库对外读模型。"""

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
            "database_name": self.database_name,
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
    """Schema 采集任务。

    它记录一次结构采集的边界与结果，关键字段包括：

    - `harvest_scope`: 本次是全量、按 schema 还是按表采集
    - `schema_names_json / table_names_json`: 用户实际选择的作用域
    - `result_payload_json / error_message`: 采集结果摘要与失败原因
    """

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


class VannaSchemaColumnAnnotation(Base):
    """字段级人工补充/覆写事实。"""

    __tablename__ = "vanna_schema_column_annotations"
    __table_args__ = (
        UniqueConstraint(
            "kb_id",
            "schema_name",
            "table_name",
            "column_name",
            name="uq_vanna_schema_column_annotation_key",
        ),
        Index(
            "ix_vanna_schema_column_annotations_kb_table",
            "kb_id",
            "schema_name",
            "table_name",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, comment="字段注释ID")
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
        String(255),
        nullable=False,
        default="",
        comment="Schema名称，空字符串表示默认schema",
    )
    table_name = Column(
        String(255), nullable=False, index=True, comment="表名称"
    )
    column_name = Column(
        String(255), nullable=False, index=True, comment="字段名称"
    )
    business_description = Column(Text, nullable=True, comment="业务说明")
    comment_override = Column(Text, nullable=True, comment="字段注释覆写")
    default_value_override = Column(Text, nullable=True, comment="默认值覆写")
    allowed_values_override_json = Column(
        JSON, nullable=True, comment="取值范围覆写（JSON格式）"
    )
    sample_values_override_json = Column(
        JSON, nullable=True, comment="示例值覆写（JSON格式）"
    )
    update_source = Column(
        String(32),
        nullable=False,
        default="manual",
        index=True,
        comment="更新来源（manual/ai_suggest/imported）",
    )
    create_user_id = Column(
        Integer, nullable=False, index=True, comment="创建用户ID"
    )
    create_user_name = Column(
        String(255), nullable=True, comment="创建用户名"
    )
    updated_by_user_id = Column(
        Integer, nullable=False, index=True, comment="最后更新用户ID"
    )
    updated_by_user_name = Column(
        String(255), nullable=True, comment="最后更新用户名"
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
    """训练知识条目。

    这是 Vanna 检索知识的标准宿主，既可以表示 question/sql 样本，
    也可以表示 schema 摘要或业务文档。阅读时重点关注：

    - `entry_type`: 决定这条知识在 Prompt 里扮演什么角色
    - `lifecycle_status / quality_status`: 决定它是否参与正式召回
    - `content_hash`: 去重与幂等更新的基础
    - `tables_read_json / columns_read_json / output_fields_json`: 为治理和资产提升提供结构线索
    """

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
    """训练知识切片。

    一条训练知识可能被切成多个 chunk 参与召回。关键字段包括：

    - `entry_id`: 反向指回原始训练条目
    - `chunk_type`: 指明属于问答对、schema 摘要还是文档
    - `embedding_vector / embedding_model`: 检索时使用的向量表示及其来源模型
    - `lifecycle_status`: 与原始条目一起控制是否允许参与召回
    """

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


class VannaSqlAssetStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class VannaSqlAssetQualityStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"


class VannaSqlAssetRunStatus(str, Enum):
    BOUND = "bound"
    EXECUTED = "executed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class VannaSqlAsset(Base):
    """正式复用的 SQL 资产宿主。

    它表示“这类查询需求已经被治理成平台资产”。关键字段包括：

    - `asset_code`: 对外稳定引用标识，工具层优先用它而不是数据库 id
    - `system_short / database_name / env`: 限定资产可复用的边界
    - `match_keywords_json / match_examples_json`: 资产检索阶段的主要语义线索
    - `current_version_id`: 当前对外生效的模板版本
    - `origin_ask_run_id / origin_training_entry_id`: 追溯资产最初从哪里沉淀而来
    """

    __tablename__ = "vanna_sql_assets"
    __table_args__ = (
        Index("ix_vanna_sql_assets_kb_status", "kb_id", "status"),
        Index("ix_vanna_sql_assets_datasource_status", "datasource_id", "status"),
        Index(
            "ix_vanna_sql_assets_system_env_status",
            "system_short",
            "env",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, comment="SQL资产ID")
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
    asset_code = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="资产唯一编码",
    )
    name = Column(String(255), nullable=False, comment="资产名称")
    description = Column(Text, nullable=True, comment="资产描述")
    intent_summary = Column(Text, nullable=True, comment="用途摘要")
    asset_kind = Column(
        String(32), nullable=False, default="query", comment="资产类型"
    )
    status = Column(
        String(32),
        nullable=False,
        default=VannaSqlAssetStatus.DRAFT.value,
        index=True,
        comment="资产状态",
    )
    system_short = Column(
        String(64), nullable=False, index=True, comment="系统简称"
    )
    database_name = Column(
        String(255), nullable=True, index=True, comment="逻辑数据库名称"
    )
    env = Column(
        String(32), nullable=False, index=True, comment="环境"
    )
    match_keywords_json = Column(
        JSON, nullable=True, default=list, comment="检索关键词"
    )
    match_examples_json = Column(
        JSON, nullable=True, default=list, comment="检索示例"
    )
    owner_user_id = Column(
        Integer, nullable=False, index=True, comment="所有者用户ID"
    )
    owner_user_name = Column(
        String(255), nullable=True, comment="所有者用户名"
    )
    current_version_id = Column(
        Integer, nullable=True, index=True, comment="当前发布版本ID"
    )
    origin_ask_run_id = Column(
        Integer,
        ForeignKey("vanna_ask_runs.id"),
        nullable=True,
        index=True,
        comment="来源Ask运行ID",
    )
    origin_training_entry_id = Column(
        Integer,
        ForeignKey("vanna_training_entries.id"),
        nullable=True,
        index=True,
        comment="来源训练条目ID",
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
        """输出资产对外读模型。"""

        return {
            "id": int(self.id),
            "kb_id": int(self.kb_id),
            "datasource_id": int(self.datasource_id),
            "asset_code": self.asset_code,
            "name": self.name,
            "description": self.description,
            "intent_summary": self.intent_summary,
            "asset_kind": self.asset_kind,
            "status": self.status,
            "system_short": self.system_short,
            "database_name": self.database_name,
            "env": self.env,
            "match_keywords": list(self.match_keywords_json or []),
            "match_examples": list(self.match_examples_json or []),
            "owner_user_id": int(self.owner_user_id),
            "owner_user_name": self.owner_user_name,
            "current_version_id": self.current_version_id,
            "origin_ask_run_id": self.origin_ask_run_id,
            "origin_training_entry_id": self.origin_training_entry_id,
            "created_at": _isoformat(self.created_at),
            "updated_at": _isoformat(self.updated_at),
        }


class VannaSqlAssetVersion(Base):
    """SQL 资产版本。

    它描述“同一个资产在某个时刻的具体模板实现”。关键字段包括：

    - `template_sql`: 真正受治理的 SQL 模板正文
    - `parameter_schema_json`: 参数契约，决定绑定层如何收参和校验
    - `tables_read_json / columns_read_json / output_fields_json`: 方便治理、审计和影响面分析
    - `quality_status / is_published`: 表示这个版本是否足够可信、是否已对外生效
    """

    __tablename__ = "vanna_sql_asset_versions"
    __table_args__ = (
        Index(
            "ix_vanna_sql_asset_versions_asset_published",
            "asset_id",
            "is_published",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, comment="SQL资产版本ID")
    asset_id = Column(
        Integer,
        ForeignKey("vanna_sql_assets.id"),
        nullable=False,
        index=True,
        comment="资产ID",
    )
    version_no = Column(Integer, nullable=False, comment="版本号")
    version_label = Column(
        String(64), nullable=True, comment="版本标签"
    )
    template_sql = Column(Text, nullable=False, comment="SQL模板")
    parameter_schema_json = Column(
        JSON, nullable=False, default=list, comment="参数契约"
    )
    render_config_json = Column(
        JSON, nullable=True, default=dict, comment="渲染配置"
    )
    statement_kind = Column(
        String(32), nullable=False, default="SELECT", comment="语句类型"
    )
    tables_read_json = Column(
        JSON, nullable=True, default=list, comment="读取表集合"
    )
    columns_read_json = Column(
        JSON, nullable=True, default=list, comment="读取列集合"
    )
    output_fields_json = Column(
        JSON, nullable=True, default=list, comment="输出字段集合"
    )
    verification_result_json = Column(
        JSON, nullable=True, default=dict, comment="验证结果"
    )
    quality_status = Column(
        String(32),
        nullable=False,
        default=VannaSqlAssetQualityStatus.UNVERIFIED.value,
        index=True,
        comment="质量状态",
    )
    is_published = Column(
        Boolean, nullable=False, default=False, comment="是否已发布"
    )
    published_at = Column(
        DateTime, nullable=True, comment="发布时间"
    )
    created_by = Column(
        String(255), nullable=True, comment="创建人"
    )
    created_at = Column(
        DateTime, default=func.now(), nullable=False, comment="创建时间"
    )

    def to_dict(self) -> Dict[str, Any]:
        """输出版本对外读模型。"""

        return {
            "id": int(self.id),
            "asset_id": int(self.asset_id),
            "version_no": int(self.version_no),
            "version_label": self.version_label,
            "template_sql": self.template_sql,
            "parameter_schema_json": list(self.parameter_schema_json or []),
            "render_config_json": dict(self.render_config_json or {}),
            "statement_kind": self.statement_kind,
            "tables_read_json": list(self.tables_read_json or []),
            "columns_read_json": list(self.columns_read_json or []),
            "output_fields_json": list(self.output_fields_json or []),
            "verification_result_json": dict(self.verification_result_json or {}),
            "quality_status": self.quality_status,
            "is_published": bool(self.is_published),
            "published_at": _isoformat(self.published_at),
            "created_by": self.created_by,
            "created_at": _isoformat(self.created_at),
        }


class VannaSqlAssetRun(Base):
    """SQL 资产执行事实。

    这是资产运行态审计表，不承载资产定义，只记录一次执行发生了什么。
    审查时重点看：

    - `asset_id / asset_version_id`: 执行的是谁、哪个版本
    - `binding_plan_json / bound_params_json`: 参数如何被解析出来
    - `compiled_sql`: 最终真正下发到数据源的 SQL
    - `execution_status / execution_result_json`: 执行是否成功以及返回了什么
    """

    __tablename__ = "vanna_sql_asset_runs"
    __table_args__ = (
        Index("ix_vanna_sql_asset_runs_asset_created", "asset_id", "created_at"),
        Index(
            "ix_vanna_sql_asset_runs_task_status",
            "task_id",
            "execution_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True, comment="SQL资产运行ID")
    asset_id = Column(
        Integer,
        ForeignKey("vanna_sql_assets.id"),
        nullable=False,
        index=True,
        comment="资产ID",
    )
    asset_version_id = Column(
        Integer,
        ForeignKey("vanna_sql_asset_versions.id"),
        nullable=False,
        index=True,
        comment="资产版本ID",
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
    task_id = Column(
        Integer, nullable=True, index=True, comment="任务ID"
    )
    question_text = Column(Text, nullable=True, comment="原始问题")
    resolved_by = Column(
        String(32), nullable=False, default="asset_search", comment="命中来源"
    )
    binding_plan_json = Column(
        JSON, nullable=True, default=dict, comment="装配计划"
    )
    bound_params_json = Column(
        JSON, nullable=True, default=dict, comment="绑定参数"
    )
    compiled_sql = Column(Text, nullable=False, comment="最终可执行SQL")
    execution_status = Column(
        String(32),
        nullable=False,
        default=VannaSqlAssetRunStatus.BOUND.value,
        index=True,
        comment="执行状态",
    )
    execution_result_json = Column(
        JSON, nullable=True, default=dict, comment="执行结果"
    )
    approval_status = Column(
        String(32), nullable=True, index=True, comment="审批状态"
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": int(self.id),
            "asset_id": int(self.asset_id),
            "asset_version_id": int(self.asset_version_id),
            "kb_id": int(self.kb_id),
            "datasource_id": int(self.datasource_id),
            "task_id": self.task_id,
            "question_text": self.question_text,
            "resolved_by": self.resolved_by,
            "binding_plan_json": dict(self.binding_plan_json or {}),
            "bound_params_json": dict(self.bound_params_json or {}),
            "compiled_sql": self.compiled_sql,
            "execution_status": self.execution_status,
            "execution_result_json": dict(self.execution_result_json or {}),
            "approval_status": self.approval_status,
            "create_user_id": int(self.create_user_id),
            "create_user_name": self.create_user_name,
            "created_at": _isoformat(self.created_at),
        }
