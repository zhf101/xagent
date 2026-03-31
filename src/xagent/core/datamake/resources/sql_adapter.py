"""
`SQL Resource Adapter`（SQL 资源适配器）模块。

这一层不开放任意 SQL，而是把受控资源动作映射到现有 xagent SQL 工具。
"""

from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from ...database.adapters import create_adapter_for_type
from ...database.adapters.sqlalchemy_common import SqlAlchemySyncAdapter
from ...database.config import database_connection_config_from_url
from ...tools.core.sql_tool import (
    _looks_like_write_operation,
    _stream_export_to_csv,
    _stream_export_to_jsonlines,
    _stream_export_to_parquet,
)
from ..contracts.constants import RUNTIME_STATUS_FAILED
from ..contracts.runtime import CompiledExecutionContract, RuntimeResult
from .sql_brain_gateway import SqlBrainGateway
from .catalog import ResourceCatalog
from .sql_resource_definition import SqlPreparedContextPayload

if TYPE_CHECKING:
    from ...workspace import TaskWorkspace


class SqlResourceAdapter:
    """
    `SqlResourceAdapter`（SQL 资源适配器）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：真正调用 SQL 资源的适配器

    关键边界：
    - 它负责把“已经准备好的 SQL 执行契约”下钻到 xagent SQL 工具
    - 它可以携带 SQL Brain 生成/校验的技术事实
    - 但它不负责决定“当前任务下一步做什么”
    """

    def __init__(self, sql_brain_gateway: SqlBrainGateway | None = None) -> None:
        self.sql_brain_gateway = sql_brain_gateway

    async def execute(
        self,
        catalog: ResourceCatalog,
        contract: CompiledExecutionContract,
    ) -> RuntimeResult:
        """
        基于编译后的执行契约调用已绑定的 xagent SQL 工具。
        """

        resource_action = catalog.get_action(contract.resource_key, contract.operation_key)
        normalizer = catalog.get_result_normalizer(resource_action)
        tool_args = contract.params.get("tool_args", contract.params)
        if not isinstance(tool_args, dict):
            tool_args = {}
        result_contract = dict(resource_action.result_contract)
        sql_brain_payload = self._extract_sql_brain_payload(contract)

        if self._should_fail_fast_for_sql(contract, tool_args):
            return RuntimeResult(
                run_id=contract.run_id,
                status=RUNTIME_STATUS_FAILED,
                summary="SQL 执行契约缺少 query，未进入真实资源调用",
                facts={
                    "normalizer": "sql_contract_guard",
                    "transport_status": "unknown",
                    "protocol_status": "unknown",
                    "business_status": "unknown",
                    **self._build_sql_context_observation_facts(contract, sql_brain_payload),
                },
                data={
                    "sql_brain": self._build_sql_brain_observation_payload(
                        contract,
                        sql_brain_payload,
                    )
                },
                error="sql_query_missing",
                evidence=[f"tool:{contract.tool_name}"],
            )

        direct_db_url = self._resolve_direct_db_url(contract, tool_args)
        if direct_db_url:
            return await self._execute_direct_sql(
                db_url=direct_db_url,
                tool_args=tool_args,
                contract=contract,
                normalizer=normalizer,
                result_contract=result_contract,
                sql_brain_payload=sql_brain_payload,
                workspace=self._resolve_workspace_for_direct_sql(
                    catalog,
                    contract.tool_name,
                ),
            )

        tool = catalog.get_tool(contract.tool_name)

        try:
            raw_result = await self._run_tool(tool, tool_args)
        except Exception as exc:
            normalized = normalizer.normalize_exception(
                exc,
                contract=contract,
                result_contract=result_contract,
            )
            return RuntimeResult(
                run_id=contract.run_id,
                status=normalized.status,
                summary=normalized.summary,
                facts=self._merge_facts(contract, normalized.facts, sql_brain_payload),
                data={
                    "raw_error": self._serialize_raw_payload(exc),
                    "sql_brain": self._build_sql_brain_observation_payload(
                        contract,
                        sql_brain_payload,
                    ),
                },
                error=normalized.error,
                evidence=self._build_evidence(contract, sql_brain_payload),
            )

        normalized = normalizer.normalize_result(
            raw_result,
            contract=contract,
            result_contract=result_contract,
        )
        return RuntimeResult(
            run_id=contract.run_id,
            status=normalized.status,
            summary=normalized.summary,
            facts=self._merge_facts(contract, normalized.facts, sql_brain_payload),
            data={
                "raw_result": self._serialize_raw_payload(raw_result),
                "sql_brain": self._build_sql_brain_observation_payload(
                    contract,
                    sql_brain_payload,
                ),
            },
            error=normalized.error,
            evidence=self._build_evidence(contract, sql_brain_payload),
        )

    async def _run_tool(self, tool: Any, tool_args: dict[str, Any]) -> Any:
        """
        统一兼容异步 / 同步 xagent 工具执行接口。
        """

        if hasattr(tool, "run_json_async"):
            return await tool.run_json_async(tool_args)
        return tool.run_json_sync(tool_args)

    def _serialize_raw_payload(self, payload: Any) -> Any:
        """
        保留 SQL 资源层原始事实，供 Runtime / Ledger 回放。
        """

        if isinstance(payload, (dict, list, str, int, float, bool)) or payload is None:
            return payload
        if hasattr(payload, "model_dump"):
            return payload.model_dump(mode="json")
        if isinstance(payload, Exception):
            return {
                "type": type(payload).__name__,
                "message": str(payload),
            }
        return str(payload)

    def _extract_sql_brain_payload(
        self,
        contract: CompiledExecutionContract,
    ) -> dict[str, Any]:
        """
        读取 Guard 预处理阶段写入的 SQL Brain 技术事实。
        """

        payload = contract.params.get("_system_sql_brain")
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    def _merge_facts(
        self,
        contract: CompiledExecutionContract,
        facts: dict[str, Any],
        sql_brain_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        把 SQL Brain 技术事实补充到 Runtime facts。
        """

        merged = dict(facts)
        if sql_brain_payload:
            merged.update(
                self._build_sql_context_observation_facts(contract, sql_brain_payload)
            )
            verification = sql_brain_payload.get("verification")
            if isinstance(verification, dict):
                merged["sql_risk_level"] = verification.get("risk_level")
                merged["sql_statement_kind"] = verification.get("statement_kind")
        return merged

    def _build_sql_context_observation_facts(
        self,
        contract: CompiledExecutionContract | None,
        sql_brain_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        生成 observation / ledger 可直接索引的 SQL 上下文来源摘要事实。

        这里是摘要层：
        - 让 UI / 审计 / 查询能快速知道“这次是否采用了 hint/source”
        - 不把完整 source 明细塞进 facts，避免 facts 退化成大对象仓库
        """

        prepared_context = SqlPreparedContextPayload.from_mapping(
            contract.params.get("_system_sql_context") if contract is not None else None
        )
        source_types = sorted(
            {
                source.match_reason
                for source in prepared_context.context_sources
                if source.match_reason
            }
        )
        return {
            "sql_brain_used": bool(sql_brain_payload),
            "sql_context_source_count": len(prepared_context.context_sources),
            "sql_context_source_types": source_types,
        }

    def _build_sql_brain_observation_payload(
        self,
        contract: CompiledExecutionContract,
        sql_brain_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        生成写入 `data.sql_brain` 的结构化观测载荷。

        这里保留完整 source 明细，便于后续：
        - observation 回放
        - ledger 审计
        - UI 展示“本次采用了哪些 sql_context source”
        """

        payload = dict(sql_brain_payload)
        prepared_context = SqlPreparedContextPayload.from_mapping(
            contract.params.get("_system_sql_context")
        )
        payload["context_sources"] = [
            source.model_dump(mode="json")
            for source in prepared_context.context_sources
        ]
        payload["context_source_count"] = len(prepared_context.context_sources)
        return payload

    def _build_evidence(
        self,
        contract: CompiledExecutionContract,
        sql_brain_payload: dict[str, Any],
    ) -> list[str]:
        """
        构建 SQL 执行证据链。
        """

        evidence = [f"tool:{contract.tool_name}"]
        if sql_brain_payload:
            evidence.append("sql_brain:prepared")
        return evidence

    def _should_fail_fast_for_sql(
        self,
        contract: CompiledExecutionContract,
        tool_args: dict[str, Any],
    ) -> bool:
        """
        对 SQL 动作做最后一道执行前契约检查。

        这里不是重新替 Guard 做治理，而是保证 Runtime 不会把一个明显不完整的
        SQL 契约继续发给底层工具。
        """

        query = tool_args.get("query")
        return not isinstance(query, str) or not query.strip()

    def _resolve_direct_db_url(
        self,
        contract: CompiledExecutionContract,
        tool_args: dict[str, Any],
    ) -> str | None:
        """
        解析 SQL 资源的直连 URL。

        适用场景：
        - 当前资源动作没有 `connection_name`
        - 但 Guard 已经通过 datasource 解析拿到了 `db_url`
        - 这时 Resource 层仍然可以完成真实调用，不要求先注册环境变量连接名
        """

        if isinstance(tool_args.get("connection_name"), str) and tool_args.get(
            "connection_name"
        ).strip():
            return None

        candidates = [
            tool_args.get("db_url"),
            contract.params.get("db_url"),
        ]
        sql_source = contract.params.get("_system_sql_datasource")
        if isinstance(sql_source, dict):
            candidates.append(sql_source.get("db_url"))
        resource_metadata = contract.metadata.get("resource_metadata")
        if isinstance(resource_metadata, dict):
            candidates.append(resource_metadata.get("db_url"))

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    async def _execute_direct_sql(
        self,
        *,
        db_url: str,
        tool_args: dict[str, Any],
        contract: CompiledExecutionContract,
        normalizer: Any,
        result_contract: dict[str, Any],
        sql_brain_payload: dict[str, Any],
        workspace: TaskWorkspace | None,
    ) -> RuntimeResult:
        """
        使用直连 `db_url` 执行 SQL。

        这条路径的定位仍然是 Resource 层真实调用，不是 Guard/SQL Brain 越权执行。
        之所以放在这里，是因为：
        - Guard 已完成治理
        - Runtime 已决定正式执行
        - Resource 当前缺的只是“如何连到数据库”这一层实现

        这里额外要兜住两个与历史工具路径一致的约束：
        - 不能把同步 SQLAlchemy 调用直接压在 asyncio 事件循环上
        - 不能因为改走 direct `db_url` 就丢失 `output_file` 导出语义
        """

        output_file = tool_args.get("output_file")
        if not isinstance(output_file, str) or not output_file.strip():
            output_file = None

        try:
            raw_result = await self._run_direct_sql_query(
                db_url=db_url,
                query=str(tool_args["query"]),
                read_only=self._resolve_direct_sql_read_only(contract, tool_args),
                output_file=output_file,
                workspace=workspace,
            )
        except Exception as exc:
            normalized = normalizer.normalize_exception(
                exc,
                contract=contract,
                result_contract=result_contract,
            )
            return RuntimeResult(
                run_id=contract.run_id,
                status=normalized.status,
                summary=normalized.summary,
                facts=self._merge_facts(contract, normalized.facts, sql_brain_payload),
                data={
                    "raw_error": self._serialize_raw_payload(exc),
                    "sql_brain": self._build_sql_brain_observation_payload(
                        contract,
                        sql_brain_payload,
                    ),
                    "direct_db_url": db_url,
                },
                error=normalized.error,
                evidence=self._build_evidence(contract, sql_brain_payload)
                + ["sql_resource:direct_db_url"],
            )

        normalized = normalizer.normalize_result(
            raw_result,
            contract=contract,
            result_contract=result_contract,
        )
        return RuntimeResult(
            run_id=contract.run_id,
            status=normalized.status,
            summary=normalized.summary,
            facts=self._merge_facts(contract, normalized.facts, sql_brain_payload),
            data={
                "raw_result": self._serialize_raw_payload(raw_result),
                "sql_brain": self._build_sql_brain_observation_payload(
                    contract,
                    sql_brain_payload,
                ),
                "direct_db_url": db_url,
            },
            error=normalized.error,
            evidence=self._build_evidence(contract, sql_brain_payload)
            + ["sql_resource:direct_db_url"],
        )

    def _resolve_workspace_for_direct_sql(
        self,
        catalog: ResourceCatalog,
        tool_name: str,
    ) -> TaskWorkspace | None:
        """
        尽量从已注册 SQL 工具上回收 workspace。

        direct `db_url` 路径本身不再强依赖工具注册，这是 Phase 1 允许的能力扩展；
        但如果当前运行期本来就挂了 SQL 工具，我们仍应复用它绑定的 workspace，
        以保持 `output_file` 与普通 `execute_sql_query` 路径一致。
        """

        try:
            tool = catalog.get_tool(tool_name)
        except KeyError:
            return None
        return self._extract_workspace_from_tool(tool)

    def _extract_workspace_from_tool(self, tool: Any) -> TaskWorkspace | None:
        """
        从工具实例里提取 workspace。

        当前 SQL 工具经常是 `FunctionTool(bound_method)` 形态，
        workspace 藏在 bound method 的宿主对象 `_workspace` 上。
        这里做保守探测，不要求所有工具都遵循同一个内部字段。
        """

        bound_owner = getattr(getattr(tool, "func", None), "__self__", None)
        candidates = (
            getattr(bound_owner, "_workspace", None),
            getattr(bound_owner, "workspace", None),
            getattr(tool, "_workspace", None),
            getattr(tool, "workspace", None),
        )
        for candidate in candidates:
            if candidate is not None and hasattr(candidate, "resolve_path"):
                return candidate
        return None

    async def _run_direct_sql_query(
        self,
        *,
        db_url: str,
        query: str,
        read_only: bool = True,
        output_file: str | None = None,
        workspace: TaskWorkspace | None = None,
    ) -> dict[str, Any]:
        """
        用线程池托管同步 SQLAlchemy 调用，避免阻塞主事件循环。

        这里故意不直接在协程里 `create_engine()/execute()`：
        - SQLAlchemy 当前仍走同步 engine
        - datamake runtime 依赖 asyncio 承载 websocket / task traffic
        - 一条慢查询不应该卡住整条事件循环
        """

        thread_kwargs: dict[str, Any] = {
            "db_url": db_url,
            "query": query,
            "output_file": output_file,
            "workspace": workspace,
        }
        if not read_only:
            thread_kwargs["read_only"] = False

        return await asyncio.to_thread(
            self._run_direct_sql_query_sync,
            **thread_kwargs,
        )

    def _run_direct_sql_query_sync(
        self,
        *,
        db_url: str,
        query: str,
        read_only: bool = True,
        output_file: str | None = None,
        workspace: TaskWorkspace | None = None,
    ) -> dict[str, Any]:
        """
        在工作线程中执行 direct SQL。

        返回结构尽量与现有 SQL tool 对齐，保证 normalizer / runtime / UI
        不需要感知“这次是 connection_name 还是 direct db_url”。
        """

        config = database_connection_config_from_url(make_url(db_url), read_only=read_only)
        adapter = self._create_adapter_if_supported(config)

        if output_file and workspace:
            streaming_url = self._resolve_direct_streaming_sqlalchemy_url(
                db_url=db_url,
                adapter=adapter,
            )
            if streaming_url is not None:
                return self._run_direct_sqlalchemy_query_sync(
                    db_url=streaming_url,
                    query=query,
                    output_file=output_file,
                    workspace=workspace,
                )

        if adapter is None:
            return self._run_direct_sqlalchemy_query_sync(
                db_url=db_url,
                query=query,
                read_only=read_only,
                output_file=output_file,
                workspace=workspace,
            )

        result = asyncio.run(self._run_query_via_adapter(adapter=adapter, query=query))

        columns = list(result.rows[0].keys()) if result.rows else []
        row_count = (
            len(result.rows)
            if result.rows
            else int(result.affected_rows or 0)
        )
        if output_file and workspace:
            exported_count = self._export_direct_sql_rows(
                workspace=workspace,
                output_file=output_file,
                rows=result.rows,
                columns=columns,
            )
            return {
                "success": True,
                "rows": [],
                "row_count": exported_count,
                "columns": columns,
                "message": (
                    "Direct SQL executed successfully, "
                    f"exported {exported_count} row(s) to {output_file}"
                ),
            }

        if result.rows:
            return {
                "success": True,
                "rows": result.rows,
                "row_count": len(result.rows),
                "columns": columns,
                "message": f"Direct SQL executed successfully, returned {len(result.rows)} row(s)",
            }

        return {
            "success": True,
            "rows": [],
            "row_count": row_count,
            "columns": columns,
            "message": f"Direct SQL executed successfully, affected {row_count} row(s)",
        }

    def _create_adapter_if_supported(self, config: Any) -> Any | None:
        """创建已纳入平台治理的 adapter；未知方言保留历史 SQLAlchemy 兼容路径。"""

        try:
            return create_adapter_for_type(config.db_type, config)
        except ValueError:
            return None

    def _resolve_direct_streaming_sqlalchemy_url(
        self,
        *,
        db_url: str,
        adapter: Any | None,
    ) -> str | None:
        """为 direct SQL 导出场景解析可流式执行的 SQLAlchemy URL。"""

        if isinstance(adapter, SqlAlchemySyncAdapter):
            try:
                return str(adapter.build_sqlalchemy_url())
            except Exception:
                return None
        if adapter is None:
            return db_url
        return None

    def _run_direct_sqlalchemy_query_sync(
        self,
        *,
        db_url: str,
        query: str,
        read_only: bool = True,
        output_file: str | None = None,
        workspace: TaskWorkspace | None = None,
    ) -> dict[str, Any]:
        """保留 direct `db_url` 的历史 SQLAlchemy 兼容/流式导出路径。"""

        stmt = text(query)
        engine = create_engine(db_url, future=True)
        try:
            with engine.connect() as connection:
                if output_file and workspace:
                    result = connection.execute(stmt)
                    exported_count, columns = self._export_direct_sql_result(
                        workspace=workspace,
                        output_file=output_file,
                        result=result,
                    )
                    return {
                        "success": True,
                        "rows": [],
                        "row_count": exported_count,
                        "columns": columns,
                        "message": (
                            "Direct SQL executed successfully, "
                            f"exported {exported_count} row(s) to {output_file}"
                        ),
                    }

                result = connection.execute(stmt)
                if result.returns_rows:
                    rows = [dict(row._mapping) for row in result.fetchall()]
                    columns = list(rows[0].keys()) if rows else list(result.keys())
                    return {
                        "success": True,
                        "rows": rows,
                        "row_count": len(rows),
                        "columns": columns,
                        "message": f"Direct SQL executed successfully, returned {len(rows)} row(s)",
                    }

                rowcount = result.rowcount if hasattr(result, "rowcount") else 0
                if not read_only and _looks_like_write_operation(query):
                    connection.commit()
                return {
                    "success": True,
                    "rows": [],
                    "row_count": int(rowcount or 0),
                    "columns": [],
                    "message": f"Direct SQL executed successfully, affected {int(rowcount or 0)} row(s)",
                }
        finally:
            engine.dispose()

    async def _run_query_via_adapter(
        self,
        *,
        adapter: Any,
        query: str,
    ) -> Any:
        """统一封装 adapter 生命周期，避免 direct 路径重复散落 connect/disconnect。"""

        await adapter.connect()
        try:
            return await adapter.execute_query(query)
        finally:
            await adapter.disconnect()

    def _export_direct_sql_result(
        self,
        *,
        workspace: TaskWorkspace,
        output_file: str,
        result: Any,
    ) -> tuple[int, list[str]]:
        """
        复用现有 SQL tool 的流式导出实现。

        这样做的原因不是“省几行代码”，而是确保 direct `db_url` 路径在
        文件格式支持、流式写出方式、列名提取规则上与既有工具保持一致。
        """

        file_ext = Path(output_file).suffix.lower()
        if file_ext == ".csv":
            _, exported_count, columns = _stream_export_to_csv(
                workspace,
                output_file,
                result,
            )
            return exported_count, columns
        if file_ext == ".parquet":
            _, exported_count, columns = _stream_export_to_parquet(
                workspace,
                output_file,
                result,
            )
            return exported_count, columns
        if file_ext in (".json", ".jsonl", ".ndjson"):
            _, exported_count, columns = _stream_export_to_jsonlines(
                workspace,
                output_file,
                result,
            )
            return exported_count, columns
        raise ValueError(
            f"Unsupported file format: {file_ext}. "
            "Supported: .csv (streaming), .parquet (streaming), "
            ".json/.jsonl/.ndjson (streaming JSON Lines)"
        )

    def _export_direct_sql_rows(
        self,
        *,
        workspace: TaskWorkspace,
        output_file: str,
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> int:
        """把 adapter 统一结果导出到 workspace。

        direct `db_url` 迁到多数据库 adapter 后，并不是每种数据库都能继续复用
        SQLAlchemy CursorResult 的流式接口，所以这里补一个统一的结果导出兜底。
        """

        resolved_path = workspace.resolve_path(output_file, default_dir="output")
        file_ext = Path(output_file).suffix.lower()

        if file_ext == ".csv":
            with open(resolved_path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns or self._infer_columns(rows))
                writer.writeheader()
                writer.writerows(rows)
            return len(rows)

        if file_ext in (".json", ".jsonl", ".ndjson"):
            with open(resolved_path, "w", encoding="utf-8") as handle:
                if file_ext == ".json":
                    json.dump(rows, handle, ensure_ascii=False, indent=2)
                else:
                    for row in rows:
                        print(json.dumps(row, ensure_ascii=False), file=handle)
            return len(rows)

        if file_ext == ".parquet":
            try:
                import pyarrow as pa  # type: ignore[import-not-found]
                import pyarrow.parquet as pq  # type: ignore[import-not-found]
            except ImportError as err:
                raise ImportError(
                    f"{err}\n"
                    "pyarrow is required for Parquet export. "
                    "Install it with: pip install pyarrow"
                )
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, resolved_path)
            return len(rows)

        raise ValueError(
            f"Unsupported file format: {file_ext}. "
            "Supported: .csv (streaming), .parquet (streaming), "
            ".json/.jsonl/.ndjson (streaming JSON Lines)"
        )

    def _infer_columns(self, rows: list[dict[str, Any]]) -> list[str]:
        """在 rows 非空但列名未显式传入时，从首行推断列名。"""

        if not rows:
            return []
        return list(rows[0].keys())

    def _resolve_direct_sql_read_only(
        self,
        contract: CompiledExecutionContract,
        tool_args: dict[str, Any],
    ) -> bool:
        """解析 direct `db_url` 路径应遵循的只读约束。"""

        candidates = [
            tool_args.get("read_only"),
            contract.params.get("read_only"),
        ]
        sql_source = contract.params.get("_system_sql_datasource")
        if isinstance(sql_source, dict):
            candidates.append(sql_source.get("read_only"))
        resource_metadata = contract.metadata.get("resource_metadata")
        if isinstance(resource_metadata, dict):
            sql_datasource = resource_metadata.get("sql_datasource")
            if isinstance(sql_datasource, dict):
                candidates.append(sql_datasource.get("read_only"))

        for candidate in candidates:
            if isinstance(candidate, bool):
                return candidate
        return True
