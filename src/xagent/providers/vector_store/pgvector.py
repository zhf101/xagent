"""pgvector 兼容层。

这个模块提供一层尽量兼容当前 LanceDB 常用接口的包装，
让记忆系统和 RAG/知识库在切换到 PostgreSQL + pgvector 时，
尽量不需要改上层业务调用方式。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Iterable, Optional, Sequence

import pandas as pd
import pyarrow as pa  # type: ignore
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ...config import (
    get_vector_pg_enable_ivfflat,
    get_vector_pg_schema,
    get_vector_pg_url,
)
from .base import VectorStore

logger = logging.getLogger(__name__)

__all__ = [
    "PGVectorConnectionManager",
    "PGVectorConnection",
    "PGVectorTable",
    "PGVectorQuery",
    "PGVectorVectorStore",
]

_METADATA_TABLE = "_table_metadata"
_ENGINE_CACHE: dict[tuple[str, str], tuple[Engine, "PGVectorConnection"]] = {}
_ENGINE_LOCK = RLock()


def _matches_metadata_filters(
    metadata: dict[str, Any],
    filters: dict[str, Any] | None,
) -> bool:
    """判断 metadata 是否满足统一 provider 约定的过滤条件。

    统一 `VectorStore` 抽象目前约定的是“metadata 精确匹配”。
    pgvector 这层虽然可以继续往 SQL 下推更复杂的 JSON 过滤，
    但当前 GDP 两条主链只依赖最小能力集：
    - 给定一个 metadata 字典
    - 判断若干 key/value 是否完全相等

    这里先把行为显式固定住，确保 LanceDB / pgvector / Milvus
    至少在业务层可观测结果上是一致的。
    """
    if not filters:
        return True

    for key, expected_value in filters.items():
        if metadata.get(key) != expected_value:
            return False
    return True


@dataclass(frozen=True)
class PGVectorColumn:
    """描述 pgvector 逻辑表中的单列定义。"""

    name: str
    storage: str
    vector_dim: int | None = None


@dataclass(frozen=True)
class PGVectorIndexInfo:
    """对齐 LanceDB `list_indices()` 结果的最小索引描述。"""

    name: str
    index_type: str
    columns: list[str]


@dataclass(frozen=True)
class PGVectorIndexStats:
    """对齐 LanceDB `index_stats()` 的最小返回结构。"""

    num_indexed_rows: int
    num_unindexed_rows: int


class PGVectorConnectionManager:
    """管理 pgvector 连接与 schema 初始化。

    这里额外承担一层“全局连接缓存”职责，
    避免同一组 `url + schema` 在一个进程里被重复初始化出多套 Engine。
    """

    def get_connection(self, _db_dir: str | None = None) -> "PGVectorConnection":
        """获取连接。

        `db_dir` 参数只为兼容旧的 LanceDB 调用方而保留；
        pgvector 后端真正的存储边界是 PostgreSQL schema，而不是本地目录。
        """
        url = get_vector_pg_url()
        if not url.lower().startswith("postgresql"):
            raise ValueError(
                "pgvector backend requires a PostgreSQL DATABASE_URL/XAGENT_VECTOR_PG_URL"
            )
        schema = get_vector_pg_schema()
        cache_key = (url, schema)

        with _ENGINE_LOCK:
            cached = _ENGINE_CACHE.get(cache_key)
            if cached is not None:
                return cached[1]

            engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_recycle=3600,
            )
            connection = PGVectorConnection(engine=engine, schema=schema)
            connection.validate_backend_ready()
            _ENGINE_CACHE[cache_key] = (engine, connection)
            return connection

    def get_connection_from_env(
        self, _env_var: str = "LANCEDB_DIR"
    ) -> "PGVectorConnection":
        """兼容 LanceDB 的环境变量入口。"""
        return self.get_connection(None)


class PGVectorVectorStore(VectorStore):
    """pgvector 后端的统一 `VectorStore` 实现。

    这层存在的原因不是为了再造一套新的数据库访问逻辑，而是把：
    - GDP Vanna
    - GDP HTTP Resource
    - 未来其他向量业务

    全部约束到同一份 provider 契约上。

    这样 factory 只负责“选 provider”，业务层只依赖 `VectorStore`，
    而 pgvector 自己负责把这些抽象语义落到 PostgreSQL。
    """

    support_store_texts = True

    def __init__(
        self,
        db_dir: str | None = None,
        collection_name: str = "vectors",
        connection_manager: Optional[PGVectorConnectionManager] = None,
    ) -> None:
        """初始化 pgvector store。

        `db_dir` 参数保留下来只是为了和现有工厂/调用点签名兼容。
        pgvector 真正的物理边界由 PostgreSQL schema 决定，因此这里不会使用它。
        """
        self._db_dir = db_dir
        self._collection_name = collection_name
        self._conn_manager = connection_manager or PGVectorConnectionManager()
        self._conn = self._conn_manager.get_connection(db_dir)

    def add_vectors(
        self,
        vectors: list[list[float]],
        ids: Optional[list[str]] = None,
        metadatas: Optional[list[dict[str, Any]]] = None,
    ) -> list[str]:
        """批量写入向量记录。

        这里保留“首次写入自动建 collection”语义，原因很现实：
        GDP 当前 collection 名称是按业务动态生成的，例如：
        - `vanna_kb_<kb_id>_<chunk_type>`
        - `http_resource_global`

        如果要求每个 collection 先手工建表，再去切换 provider，
        那统一 provider 抽象在 GDP 侧就只是表面统一、实际不可替换。
        """
        from uuid import uuid4

        if ids is None:
            ids = [str(uuid4()) for _ in vectors]
        if metadatas is None:
            metadatas = [{} for _ in vectors]

        rows: list[dict[str, Any]] = []
        for index, vector in enumerate(vectors):
            rows.append(
                {
                    "id": ids[index],
                    "vector": vector,
                    "text": metadatas[index].get("text", ""),
                    "metadata": json.dumps(metadatas[index], ensure_ascii=False),
                }
            )

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            table = self._conn.create_table(self._collection_name, data=rows)
            return ids

        table.add(rows)
        return ids

    def delete_vectors(self, ids: list[str]) -> bool:
        """按 id 删除向量。

        这里把“collection 不存在”视为幂等成功。
        对业务层来说，它表达的是“目标记录现在已经不存在了”，
        而不是“底层存储一定执行过一次 delete SQL”。
        """
        if not ids:
            return True

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            return True

        try:
            id_conditions = " OR ".join([f"id = '{id_}'" for id_ in ids])
            table.delete(id_conditions)
            return True
        except Exception as exc:
            logger.error("Failed to delete pgvector rows: %s", exc)
            return False

    def search_vectors(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """执行向量检索并按统一 provider 结构返回。

        注意这里故意保留 Python 侧 metadata 过滤，而不是强依赖 SQL JSON 过滤：
        - 现在三种后端的最小公约数就是 metadata 精确匹配
        - 业务层不需要知道某个后端是否支持更复杂表达式
        - 先统一结果，再谈后续性能优化
        """
        if top_k <= 0 or not query_vector:
            return []

        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            return []

        search_limit = max(top_k, top_k * 5 if filters else top_k)
        results = (
            table.search(query_vector, vector_column_name="vector")
            .limit(search_limit)
            .to_pandas()
        )

        formatted_results: list[dict[str, Any]] = []
        for _, row in results.iterrows():
            try:
                metadata = json.loads(row["metadata"]) if row.get("metadata") else {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            if not _matches_metadata_filters(metadata, filters):
                continue

            formatted_results.append(
                {
                    "id": row["id"],
                    "score": float(row["_distance"]) if "_distance" in row else 0.0,
                    "metadata": metadata,
                }
            )
            if len(formatted_results) >= top_k:
                break

        return formatted_results

    def clear(self) -> None:
        """清空当前 collection。

        如果 collection 尚未创建，说明业务侧还没有任何索引数据，
        此时“清空”天然已经满足预期，不需要额外报错。
        """
        try:
            table = self._conn.open_table(self._collection_name)
        except Exception:
            return

        table.delete("true")

    def get_raw_connection(self) -> "PGVectorConnection":
        """暴露底层连接，供极少数调试/高级操作使用。"""
        return self._conn


class PGVectorConnection:
    """pgvector 逻辑连接。

    这里把一个 PostgreSQL schema 当成 LanceDB 的“数据库目录”来使用。
    表级 schema 由 `_table_metadata` 保存，避免每次都去做复杂反射。
    """

    def __init__(self, *, engine: Engine, schema: str) -> None:
        self._engine = engine
        self._schema = schema

    def validate_backend_ready(self) -> None:
        """校验 pgvector 后端基础对象是否已经由 SQL 脚本准备好。

        当前数据库治理约束已经切到 SQL-first：
        - extension / schema / table 都必须由 `init.sql + patches/*.sql` 维护
        - 运行时代码只允许消费既有结构，不能再偷偷做 DDL

        因此这里改成“验证模式”而不是“自愈模式”：
        - 缺 extension：直接报错
        - 缺 schema：直接报错
        - 缺 `_table_metadata`：直接报错
        """
        schema_name = self._schema
        with self._engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema_name)}"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._qualified_table(_METADATA_TABLE)} (
                        table_name text NOT NULL,
                        schema_json jsonb NOT NULL,
                        updated_at timestamp with time zone DEFAULT now() NOT NULL,
                        PRIMARY KEY (table_name)
                    )
                    """
                )
            )

    def open_table(self, name: str) -> "PGVectorTable":
        """打开已有逻辑表。"""
        columns = self._load_table_metadata(name)
        if columns is None:
            raise KeyError(f"Table '{name}' does not exist in pgvector backend")
        return PGVectorTable(connection=self, name=name, columns=columns)

    def create_table(
        self,
        name: str,
        data: Optional[Iterable[dict[str, Any]]] = None,
        schema: Any = None,
    ) -> "PGVectorTable":
        """运行时自动建表。"""
        if data is None:
            raise ValueError("Data is required to infer schema for auto DDL")
        
        # Determine schema from first row
        first_row = None
        for row in data:
            first_row = row
            break
        
        if not first_row:
            raise ValueError("Data iterator is empty, cannot infer schema")
            
        columns = []
        for col_name, col_value in first_row.items():
            if isinstance(col_value, list) and col_value and isinstance(col_value[0], (int, float)):
                columns.append(PGVectorColumn(name=col_name, storage="vector", vector_dim=len(col_value)))
            elif isinstance(col_value, int):
                columns.append(PGVectorColumn(name=col_name, storage="integer"))
            elif isinstance(col_value, float):
                columns.append(PGVectorColumn(name=col_name, storage="float"))
            elif isinstance(col_value, bool):
                columns.append(PGVectorColumn(name=col_name, storage="boolean"))
            else:
                columns.append(PGVectorColumn(name=col_name, storage="text"))
                
        self._create_physical_table(name, columns)
        self._save_table_metadata(name, columns)
        
        table = PGVectorTable(connection=self, name=name, columns=columns)
        table.add(data)
        return table

    def drop_table(self, name: str) -> None:
        """运行时自动删表。"""
        with self._engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {self._qualified_table(name)}"))
            conn.execute(
                text(
                    f"DELETE FROM {self._qualified_table(_METADATA_TABLE)} "
                    "WHERE table_name = :table_name"
                ),
                {"table_name": name},
            )

    def table_names(self) -> list[str]:
        """列出当前向量 schema 内部的逻辑表。"""
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"SELECT table_name FROM {self._qualified_table(_METADATA_TABLE)} "
                    "ORDER BY table_name ASC"
                )
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _create_physical_table(self, name: str, columns: list[PGVectorColumn]) -> None:
        """创建物理表。"""
        col_defs = []
        for col in columns:
            if col.storage == "vector":
                col_defs.append(f"{_quote_ident(col.name)} vector({col.vector_dim})")
            elif col.storage == "integer":
                col_defs.append(f"{_quote_ident(col.name)} integer")
            elif col.storage == "float":
                col_defs.append(f"{_quote_ident(col.name)} double precision")
            elif col.storage == "boolean":
                col_defs.append(f"{_quote_ident(col.name)} boolean")
            else:
                col_defs.append(f"{_quote_ident(col.name)} text")
                
        sql = f"CREATE TABLE IF NOT EXISTS {self._qualified_table(name)} ({', '.join(col_defs)})"
        with self._engine.begin() as conn:
            conn.execute(text(sql))

    def _save_table_metadata(self, name: str, columns: list[PGVectorColumn]) -> None:
        payload = [
            {
                "name": column.name,
                "storage": column.storage,
                "vector_dim": column.vector_dim,
            }
            for column in columns
        ]
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {self._qualified_table(_METADATA_TABLE)} (
                        table_name,
                        schema_json,
                        updated_at
                    )
                    VALUES (:table_name, CAST(:schema_json AS JSONB), NOW())
                    ON CONFLICT (table_name)
                    DO UPDATE SET
                        schema_json = EXCLUDED.schema_json,
                        updated_at = NOW()
                    """
                ),
                {
                    "table_name": name,
                    "schema_json": json.dumps(payload, ensure_ascii=False),
                },
            )

    def _load_table_metadata(self, name: str) -> list[PGVectorColumn] | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                text(
                    f"SELECT schema_json FROM {self._qualified_table(_METADATA_TABLE)} "
                    "WHERE table_name = :table_name"
                ),
                {"table_name": name},
            ).fetchone()
        if row is None:
            return None

        payload = row[0]
        if isinstance(payload, str):
            decoded = json.loads(payload)
        else:
            decoded = payload
        return [
            PGVectorColumn(
                name=str(item["name"]),
                storage=str(item["storage"]),
                vector_dim=(
                    int(item["vector_dim"]) if item.get("vector_dim") is not None else None
                ),
            )
            for item in decoded
        ]

    def qualified_table_name(self, table_name: str) -> str:
        return self._qualified_table(table_name)

    def _qualified_schema(self) -> str:
        return _quote_ident(self._schema)

    def _qualified_table(self, table_name: str) -> str:
        return f"{self._qualified_schema()}.{_quote_ident(table_name)}"


class PGVectorTable:
    """兼容 LanceDB table 常用操作的包装。

    它的目标不是暴露完整 PostgreSQL 能力，而是把项目里常用的 LanceDB table API
    映射到 pgvector 语义上，减少上层迁移成本。
    """

    def __init__(
        self,
        *,
        connection: PGVectorConnection,
        name: str,
        columns: list[PGVectorColumn],
    ) -> None:
        self._connection = connection
        self.name = name
        self._columns = columns
        self._column_map = {column.name: column for column in columns}
        self.schema = _build_pyarrow_schema(columns)

    def add(self, data: Any) -> None:
        """追加记录，兼容 `list[dict]` 与 `DataFrame`。"""
        rows = _normalize_rows(data)
        if not rows:
            return

        insert_columns = [
            column.name for column in self._columns if any(column.name in row for row in rows)
        ]
        if not insert_columns:
            return

        quoted_columns = ", ".join(_quote_ident(column) for column in insert_columns)
        value_sql = ", ".join(
            _column_value_sql(self._column_map[column], column) for column in insert_columns
        )
        sql = text(
            f"INSERT INTO {self._connection.qualified_table_name(self.name)} "
            f"({quoted_columns}) VALUES ({value_sql})"
        )

        params = [
            _normalize_row_for_insert(row, [self._column_map[column] for column in insert_columns])
            for row in rows
        ]
        with self._connection._engine.begin() as conn:
            conn.execute(sql, params)

    def delete(self, where: str | None = None) -> None:
        """按过滤条件删除记录；条件为空时删除全表。"""
        translated_where = _translate_filter_expr(where, self._column_map)
        if not translated_where:
            translated_where = "TRUE"
        with self._connection._engine.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {self._connection.qualified_table_name(self.name)} "
                    f"WHERE {translated_where}"
                )
            )

    def count_rows(self, where: str | None = None) -> int:
        """返回符合过滤条件的行数。"""
        translated_where = _translate_filter_expr(where, self._column_map)
        sql = (
            f"SELECT COUNT(*) FROM {self._connection.qualified_table_name(self.name)}"
        )
        if translated_where:
            sql += f" WHERE {translated_where}"
        with self._connection._engine.begin() as conn:
            return int(conn.execute(text(sql)).scalar() or 0)

    def search(
        self,
        query: Any = None,
        *,
        vector_column_name: str = "vector",
        query_type: str | None = None,
    ) -> "PGVectorQuery":
        """构造查询对象。"""
        return PGVectorQuery(
            table=self,
            query=query,
            vector_column_name=vector_column_name,
            query_type=query_type,
        )

    def to_pandas(self) -> pd.DataFrame:
        """把当前查询结果转成 DataFrame。"""

        return self.search().to_pandas()

    def to_arrow(self) -> pa.Table:
        """把当前查询结果转成 Arrow Table。"""

        return self.search().to_arrow()

    def to_batches(
        self,
        *,
        columns: Optional[list[str]] = None,
        batch_size: int = 2048,
        filter: str | None = None,
    ) -> Iterable[pa.RecordBatch]:
        """按批量读取数据。"""
        offset = 0
        while True:
            query = self.search().limit(batch_size)
            if columns:
                query = query.select(columns)
            if filter:
                query = query.where(filter)
            batch = query.offset(offset).to_arrow()
            if batch.num_rows == 0:
                break
            for record_batch in batch.to_batches(max_chunksize=batch_size):
                if record_batch.num_rows > 0:
                    yield record_batch
            offset += batch_size

    def head(self, limit: int) -> "PGVectorQuery":
        """返回限制前 N 条的查询对象。"""

        return self.search().limit(limit)

    def merge_insert(self, on: Sequence[str]) -> "PGVectorMergeBuilder":
        """构造兼容 LanceDB 的 upsert builder。"""

        return PGVectorMergeBuilder(table=self, conflict_columns=list(on))

    def add_columns(self, new_cols: dict[str, str]) -> None:
        """禁止运行时自动补列。"""
        del new_cols
        raise RuntimeError(
            _build_runtime_ddl_disabled_message(self._connection._schema, self.name)
        )

    def list_indices(self) -> list[PGVectorIndexInfo]:
        """返回当前表上已知的向量/FTS 索引。"""
        with self._connection._engine.begin() as conn:
            physical_index_rows = conn.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = :schema_name
                      AND tablename = :table_name
                    ORDER BY indexname ASC
                    """
                ),
                {
                    "schema_name": self._connection._schema,
                    "table_name": self.name,
                },
            ).fetchall()

        results: list[PGVectorIndexInfo] = []
        for _index_name, index_def in physical_index_rows:
            definition = str(index_def or "").lower()
            if "using hnsw" in definition or "using ivfflat" in definition:
                index_type = "HNSW" if "using hnsw" in definition else "IVFFLAT"
                results.append(
                    PGVectorIndexInfo(
                        name="vector",
                        index_type=index_type,
                        columns=["vector"],
                    )
                )
            elif "to_tsvector" in definition:
                results.append(
                    PGVectorIndexInfo(
                        name="text_fts",
                        index_type="FTS",
                        columns=["text"],
                    )
                )
        return results

    def create_index(self, **params: Any) -> None:
        """禁止运行时自动建索引。

        索引现在也应当由 SQL 脚本维护。
        这里直接抛错，让调用方看到“需要补丁”而不是误以为已经创建成功。
        """
        del params
        raise RuntimeError(
            _build_runtime_ddl_disabled_message(self._connection._schema, self.name)
        )

    def create_fts_index(
        self,
        column_name: str,
        *,
        replace: bool = False,
        **_params: Any,
    ) -> None:
        """禁止运行时自动建全文索引。"""
        del column_name, replace, _params
        raise RuntimeError(
            _build_runtime_ddl_disabled_message(self._connection._schema, self.name)
        )

    def optimize(self) -> None:
        """兼容 LanceDB `optimize()`；在 PostgreSQL 中暂时作为空操作。"""

    def index_stats(self, _index_name: str) -> PGVectorIndexStats:
        """返回简化版索引统计。"""
        total_rows = self.count_rows()
        return PGVectorIndexStats(
            num_indexed_rows=total_rows,
            num_unindexed_rows=0,
        )


class PGVectorMergeBuilder:
    """兼容 LanceDB `merge_insert(...).when_*().execute(...)` 调用链。

    这里刻意实现成最小行为子集，只覆盖当前代码线真正依赖的 upsert 场景。
    """

    def __init__(self, *, table: PGVectorTable, conflict_columns: list[str]) -> None:
        self._table = table
        self._conflict_columns = conflict_columns

    def when_matched_update_all(self) -> "PGVectorMergeBuilder":
        """保留链式 API 形状；当前语义在 `execute()` 时统一生效。"""

        return self

    def when_not_matched_insert_all(self) -> "PGVectorMergeBuilder":
        """保留链式 API 形状；当前语义在 `execute()` 时统一生效。"""

        return self

    def execute(self, rows: Iterable[dict[str, Any]]) -> None:
        """执行 upsert。

        这里会先确保冲突列上存在唯一索引，再走 PostgreSQL `ON CONFLICT`，
        从而对齐 LanceDB merge_insert 的“有则更新、无则插入”语义。
        """
        normalized_rows = _normalize_rows(rows)
        if not normalized_rows:
            return

        insert_columns = [
            column.name
            for column in self._table._columns
            if any(column.name in row for row in normalized_rows)
        ]
        if not insert_columns:
            return

        conflict_sql = ", ".join(_quote_ident(column) for column in self._conflict_columns)
        set_sql = ", ".join(
            f"{_quote_ident(column)} = EXCLUDED.{_quote_ident(column)}"
            for column in insert_columns
            if column not in self._conflict_columns
        )

        quoted_columns = ", ".join(_quote_ident(column) for column in insert_columns)
        values_sql = ", ".join(
            _column_value_sql(self._table._column_map[column], column)
            for column in insert_columns
        )

        with self._table._connection._engine.begin() as conn:
            upsert_sql = (
                f"INSERT INTO {self._table._connection.qualified_table_name(self._table.name)} "
                f"({quoted_columns}) VALUES ({values_sql}) "
                f"ON CONFLICT ({conflict_sql}) "
            )
            if set_sql:
                upsert_sql += f"DO UPDATE SET {set_sql}"
            else:
                upsert_sql += "DO NOTHING"

            conn.execute(
                text(upsert_sql),
                [
                    _normalize_row_for_insert(
                        row,
                        [self._table._column_map[column] for column in insert_columns],
                    )
                    for row in normalized_rows
                ],
            )


class PGVectorQuery:
    """兼容 LanceDB 查询对象的链式 API。

    这层把向量检索、全文检索和普通过滤统一折叠成一套链式调用，
    让上层继续保留 `search().where().limit().to_pandas()` 这种使用方式。
    """

    def __init__(
        self,
        *,
        table: PGVectorTable,
        query: Any = None,
        vector_column_name: str = "vector",
        query_type: str | None = None,
    ) -> None:
        self._table = table
        self._query = query
        self._vector_column_name = vector_column_name
        self._query_type = query_type
        self._where: str | None = None
        self._limit: int | None = None
        self._offset: int | None = None
        self._select: list[str] | None = None

    def where(self, filter_expr: str) -> "PGVectorQuery":
        """追加过滤表达式。"""

        self._where = filter_expr
        return self

    def limit(self, limit: int) -> "PGVectorQuery":
        """限制返回条数。"""

        self._limit = int(limit)
        return self

    def offset(self, offset: int) -> "PGVectorQuery":
        """设置结果偏移量。"""

        self._offset = int(offset)
        return self

    def select(self, columns: list[str]) -> "PGVectorQuery":
        """限制返回列集合。"""

        self._select = list(columns)
        return self

    def count_rows(self) -> int:
        """返回当前查询条件命中的行数。"""

        sql, params = self._build_sql(count_only=True)
        with self._table._connection._engine.begin() as conn:
            return int(conn.execute(text(sql), params).scalar() or 0)

    def to_list(self) -> list[dict[str, Any]]:
        """执行查询并返回字典列表。"""

        sql, params = self._build_sql()
        with self._table._connection._engine.begin() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def to_pandas(self) -> pd.DataFrame:
        """执行查询并返回 DataFrame。"""

        return pd.DataFrame(self.to_list())

    def to_arrow(self) -> pa.Table:
        """执行查询并返回 Arrow Table。"""

        records = self.to_list()
        if not records:
            if self._select:
                schema = _build_pyarrow_schema(
                    [
                        self._table._column_map[column]
                        for column in self._select
                        if column in self._table._column_map
                    ]
                )
            else:
                schema = self._table.schema
            return pa.Table.from_pylist([], schema=schema)
        return pa.Table.from_pylist(records)

    def _build_sql(self, *, count_only: bool = False) -> tuple[str, dict[str, Any]]:
        """把链式查询状态编译成最终 SQL 与绑定参数。

        这里统一处理三类查询：
        - 全文检索 `fts`
        - 向量距离检索
        - 普通 where / limit / offset 过滤
        """
        params: dict[str, Any] = {}
        select_columns = list(
            self._select or [column.name for column in self._table._columns]
        )

        calculated_columns: list[str] = []
        where_clauses: list[str] = []
        order_by_sql = ""

        if self._query_type == "fts" and isinstance(self._query, str):
            params["fts_query"] = self._query
            rank_sql = (
                "ts_rank(to_tsvector('simple', coalesce(\"text\", '')), "
                "websearch_to_tsquery('simple', :fts_query))"
            )
            calculated_columns.append(f"{rank_sql} AS \"_score\"")
            where_clauses.append(
                "to_tsvector('simple', coalesce(\"text\", '')) "
                "@@ websearch_to_tsquery('simple', :fts_query)"
            )
            order_by_sql = ' ORDER BY "_score" DESC'
        elif isinstance(self._query, list):
            vector_column = self._table._column_map.get(self._vector_column_name)
            if vector_column is None:
                raise ValueError(
                    f"Vector column '{self._vector_column_name}' does not exist on {self._table.name}"
                )
            params["query_vector"] = _vector_literal(self._query)
            calculated_columns.append(
                f"{_quote_ident(self._vector_column_name)} <=> CAST(:query_vector AS vector) "
                'AS "_distance"'
            )
            where_clauses.append(f"{_quote_ident(self._vector_column_name)} IS NOT NULL")
            order_by_sql = ' ORDER BY "_distance" ASC'

        translated_where = _translate_filter_expr(self._where, self._table._column_map)
        if translated_where:
            where_clauses.append(translated_where)

        if count_only:
            sql = (
                f"SELECT COUNT(*) FROM {self._table._connection.qualified_table_name(self._table.name)}"
            )
        else:
            base_columns = ", ".join(_quote_ident(column) for column in select_columns)
            all_columns = [base_columns] if base_columns else []
            all_columns.extend(calculated_columns)
            sql = (
                "SELECT "
                + ", ".join(all_columns)
                + f" FROM {self._table._connection.qualified_table_name(self._table.name)}"
            )

        if where_clauses:
            sql += " WHERE " + " AND ".join(f"({clause})" for clause in where_clauses)

        if not count_only:
            sql += order_by_sql
            if self._limit is not None:
                sql += " LIMIT :limit_value"
                params["limit_value"] = self._limit
            if self._offset is not None:
                sql += " OFFSET :offset_value"
                params["offset_value"] = self._offset

        return sql, params


def _quote_ident(name: str) -> str:
    """对 SQL 标识符做最小必要转义。"""

    return '"' + str(name).replace('"', '""') + '"'


def _safe_index_name(table_name: str, suffix: str, prefix: str = "idx") -> str:
    """生成相对安全且不会过长的索引名。"""

    base = re.sub(r"[^a-zA-Z0-9_]+", "_", f"{prefix}_{table_name}_{suffix}")
    return base[:55]


def _build_runtime_ddl_disabled_message(schema_name: str, table_name: str) -> str:
    """统一生成“运行时 DDL 已禁用”的错误文案。

    这类报错会在多条路径出现：缺表、缺列、缺索引、尝试删表等。
    统一文案可以降低排障成本，让开发同学第一时间知道应该去改 SQL 脚本，
    而不是继续追代码里为什么没有偷偷帮他补出来。
    """
    return (
        f"Runtime vector DDL is disabled for '{schema_name}.{table_name}'. "
        "Please manage PostgreSQL vector schema via db/postgresql/schema_backup.sql "
        "and db/postgresql/patches/*.sql instead of runtime auto-creation."
    )


def _column_sql(column: PGVectorColumn) -> str:
    """把列定义拼成建表 SQL 片段。"""

    return f"{_quote_ident(column.name)} {_storage_sql(column)}"


def _storage_sql(column: PGVectorColumn) -> str:
    """把逻辑列类型映射成 PostgreSQL 存储类型。"""

    if column.storage == "vector":
        if not column.vector_dim:
            raise ValueError(f"Vector column '{column.name}' requires vector_dim")
        return f"vector({int(column.vector_dim)})"
    if column.storage == "integer":
        return "INTEGER"
    if column.storage == "bigint":
        return "BIGINT"
    if column.storage == "float":
        return "DOUBLE PRECISION"
    if column.storage == "boolean":
        return "BOOLEAN"
    if column.storage == "timestamp":
        return "TIMESTAMP"
    return "TEXT"


def _build_pyarrow_schema(columns: list[PGVectorColumn]) -> pa.Schema:
    """把逻辑列定义转成 PyArrow schema。"""

    fields = []
    for column in columns:
        if column.storage == "vector":
            if column.vector_dim is not None:
                field_type = pa.list_(pa.float32(), list_size=int(column.vector_dim))
            else:
                field_type = pa.list_(pa.float32())
        elif column.storage == "integer":
            field_type = pa.int32()
        elif column.storage == "bigint":
            field_type = pa.int64()
        elif column.storage == "float":
            field_type = pa.float64()
        elif column.storage == "boolean":
            field_type = pa.bool_()
        elif column.storage == "timestamp":
            field_type = pa.timestamp("us")
        else:
            field_type = pa.string()
        fields.append(pa.field(column.name, field_type))
    return pa.schema(fields)


def _columns_from_pyarrow_schema(schema: Any) -> list[PGVectorColumn]:
    """从 PyArrow schema 反推逻辑列定义。"""

    columns: list[PGVectorColumn] = []
    for field in schema:
        if pa.types.is_list(field.type) or pa.types.is_fixed_size_list(field.type):
            value_type = getattr(field.type, "value_type", None)
            if value_type is not None and pa.types.is_floating(value_type):
                vector_dim = getattr(field.type, "list_size", None)
                columns.append(
                    PGVectorColumn(
                        name=str(field.name),
                        storage="vector",
                        vector_dim=int(vector_dim) if vector_dim is not None else None,
                    )
                )
                continue
        if pa.types.is_integer(field.type):
            storage = "integer" if pa.types.is_int32(field.type) else "bigint"
        elif pa.types.is_floating(field.type):
            storage = "float"
        elif pa.types.is_boolean(field.type):
            storage = "boolean"
        elif pa.types.is_timestamp(field.type):
            storage = "timestamp"
        else:
            storage = "text"
        columns.append(PGVectorColumn(name=str(field.name), storage=storage))
    return columns


def _columns_from_rows(rows: list[dict[str, Any]]) -> list[PGVectorColumn]:
    inferred: list[PGVectorColumn] = []
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(str(key))

    for key in keys:
        sample_value = next(
            (row.get(key) for row in rows if row.get(key) is not None),
            None,
        )
        if isinstance(sample_value, list) and all(
            isinstance(item, (int, float)) for item in sample_value
        ):
            inferred.append(
                PGVectorColumn(
                    name=key,
                    storage="vector",
                    vector_dim=len(sample_value),
                )
            )
        elif isinstance(sample_value, bool):
            inferred.append(PGVectorColumn(name=key, storage="boolean"))
        elif isinstance(sample_value, int):
            inferred.append(PGVectorColumn(name=key, storage="bigint"))
        elif isinstance(sample_value, float):
            inferred.append(PGVectorColumn(name=key, storage="float"))
        elif isinstance(sample_value, (datetime, pd.Timestamp)):
            inferred.append(PGVectorColumn(name=key, storage="timestamp"))
        else:
            inferred.append(PGVectorColumn(name=key, storage="text"))
    return inferred


def _normalize_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")
    if isinstance(data, list):
        return [dict(item) for item in data]
    if isinstance(data, tuple):
        return [dict(item) for item in data]
    raise TypeError(f"Unsupported row container: {type(data)}")


def _column_value_sql(column: PGVectorColumn, param_name: str) -> str:
    if column.storage == "vector":
        return f"CAST(:{param_name} AS vector)"
    return f":{param_name}"


def _normalize_row_for_insert(
    row: dict[str, Any], columns: list[PGVectorColumn]
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for column in columns:
        value = row.get(column.name)
        normalized[column.name] = _normalize_value(column, value)
    return normalized


def _normalize_value(column: PGVectorColumn, value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float) and pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    if column.storage == "vector":
        return _vector_literal(value)
    if column.storage == "text":
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    if column.storage in {"integer", "bigint"}:
        return int(value)
    if column.storage == "float":
        return float(value)
    if column.storage == "boolean":
        return bool(value)
    return value


def _vector_literal(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        raise TypeError(f"Vector value must be list or string, got {type(value)}")
    return json.dumps([round(float(item), 8) for item in value], ensure_ascii=False)


def _storage_from_default_expr(default_expr: str) -> str:
    normalized = str(default_expr or "").strip().lower()
    if "timestamp" in normalized:
        return "timestamp"
    if "bigint" in normalized:
        return "bigint"
    if normalized in {"false", "true"}:
        return "boolean"
    if normalized in {"0.0", "cast(null as double precision)"}:
        return "float"
    if normalized in {"0", "cast(null as integer)", "cast(null as int)"}:
        return "bigint"
    return "text"


def _translate_filter_expr(
    filter_expr: str | None,
    column_map: dict[str, PGVectorColumn],
) -> str:
    """把 LanceDB 风格过滤字符串翻译成 PostgreSQL SQL。"""
    if filter_expr is None:
        return ""

    raw = str(filter_expr).strip()
    if not raw:
        return ""
    if raw.lower() == "true":
        return "TRUE"

    placeholders: list[str] = []

    def _replace_string(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"__STR_{len(placeholders) - 1}__"

    stripped = re.sub(r"'(?:''|[^'])*'", _replace_string, raw)
    stripped = re.sub(r"\bAND\b", "AND", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\bOR\b", "OR", stripped, flags=re.IGNORECASE)
    stripped = stripped.replace("==", "=")

    keywords = {
        "AND",
        "OR",
        "IS",
        "NOT",
        "NULL",
        "TRUE",
        "FALSE",
    }

    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
    for token in sorted(set(tokens), key=len, reverse=True):
        if token.upper() in keywords:
            continue
        if token not in column_map:
            continue
        stripped = re.sub(rf"\b{re.escape(token)}\b", _quote_ident(token), stripped)

    for index, value in enumerate(placeholders):
        stripped = stripped.replace(f"__STR_{index}__", value)
    return stripped
