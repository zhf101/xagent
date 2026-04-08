"""Vanna ask 主链路服务。

这个模块承接的是“用户提问后，平台如何尽量给出可执行 SQL”这一条主链路。
它本身不关心前端页面或工具形态，只关心后端编排顺序是否稳定：

1. 解析本次请求要落到哪个知识库
2. 从 question/sql、schema、documentation 三类知识中做召回
3. 在检索不足时补实时 schema，避免冷启动完全无上下文
4. 调大模型生成 SQL，并把生成快照完整落库
5. 按需执行 SQL，并把成功结果沉淀为候选训练样本
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from xagent.gdp.vanna.adapter.database.adapters import create_adapter_for_type
from xagent.gdp.vanna.adapter.database.config import database_connection_config_from_url
from xagent.gdp.vanna.model.text2sql import Text2SQLDatabase
from xagent.gdp.vanna.model.vanna import (
    VannaAskExecutionStatus,
    VannaAskRun,
    VannaKnowledgeBase,
)
from xagent.web.services.model_service import get_default_model
from .contracts import AskResult, RetrievalResult
from .errors import VannaDatasourceNotFoundError, VannaGenerationError
from .knowledge_base_service import KnowledgeBaseService
from .prompt_builder import PromptBuilder
from .retrieval_service import RetrievalService
from .train_service import TrainService

logger = logging.getLogger(__name__)


class AskService:
    """负责召回、组 Prompt、生成 SQL、可选执行与候选回流。

    可以把 ask 理解成一条标准流水线：
    1. 找到当前 datasource 对应的知识库
    2. 从训练条目 / schema / 文档里做召回
    3. 必要时补充实时 schema 上下文
    4. 拼 Prompt 调大模型生成 SQL
    5. 可选直接执行
    6. 可选把成功样本回流成候选训练条目
    """

    def __init__(
        self,
        db: Session,
        *,
        retrieval_service: RetrievalService | None = None,
        prompt_builder: PromptBuilder | None = None,
        llm_callable: Callable[..., Any] | None = None,
        llm_resolver: Callable[[int | None], Any] | None = None,
        sql_executor: Callable[..., Any] | None = None,
        schema_loader: Callable[..., Any] | None = None,
        train_service: TrainService | None = None,
    ) -> None:
        self.db = db
        self.kb_service = KnowledgeBaseService(db)
        self.retrieval_service = retrieval_service or RetrievalService(db)
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.llm_callable = llm_callable
        self.llm_resolver = llm_resolver or get_default_model
        self.sql_executor = sql_executor
        self.schema_loader = schema_loader
        self.train_service = train_service or TrainService(db)

    async def ask(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        question: str,
        kb_id: int | None = None,
        task_id: int | None = None,
        top_k_sql: int | None = None,
        top_k_schema: int | None = None,
        top_k_doc: int | None = None,
        auto_run: bool = False,
        auto_train_on_success: bool = False,
    ) -> AskResult:
        """执行一次 ask 请求并返回结构化结果。

        输入语义：
        - `datasource_id` / `kb_id` 决定本次问题落在哪个数据语境里
        - `owner_user_id` 用于权限收缩，确保只能访问当前用户自己的 datasource / kb
        - `auto_run` 决定是否只预览 SQL，还是直接执行
        - `auto_train_on_success` 决定是否把成功样本回流为候选训练条目

        状态影响：
        - 会落库一条 `VannaAskRun`
        - 会刷新知识库的 `last_ask_at`
        - 在 `auto_train_on_success=True` 且满足条件时，会新增训练条目
        """
        kb = self._resolve_kb(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
            create_user_name=create_user_name,
            kb_id=kb_id,
        )
        normalized_question = str(question or "").strip()
        retrieval = self.retrieval_service.retrieve(
            kb_id=int(kb.id),
            question=normalized_question,
            system_short=kb.system_short,
            env=kb.env,
            top_k_sql=top_k_sql or kb.default_top_k_sql or 8,
            top_k_schema=top_k_schema or kb.default_top_k_schema or 12,
            top_k_doc=top_k_doc or kb.default_top_k_doc or 6,
        )
        live_schema_context = await self._maybe_load_live_schema_context(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            question=normalized_question,
            retrieval=retrieval,
        )
        prompt_bundle = self.prompt_builder.build_prompt(
            kb=kb,
            question=normalized_question,
            retrieval=retrieval,
            live_schema_context=live_schema_context,
        )
        generation = await self._generate_sql(
            kb=kb,
            owner_user_id=owner_user_id,
            question=normalized_question,
            prompt_bundle=prompt_bundle,
            retrieval=retrieval,
        )

        # ask_run 是主链路审计事实。即使后续不执行 SQL，也要把检索快照、
        # Prompt 快照和生成结果留下来，便于问题追查与训练回放。
        ask_run = VannaAskRun(
            kb_id=int(kb.id),
            datasource_id=int(kb.datasource_id),
            system_short=kb.system_short,
            env=kb.env,
            task_id=task_id,
            question_text=normalized_question,
            rewritten_question=normalized_question,
            retrieval_snapshot_json=retrieval.to_dict(),
            prompt_snapshot_json={
                **prompt_bundle["snapshot"],
                "system_prompt": prompt_bundle["system_prompt"],
                "user_prompt": prompt_bundle["user_prompt"],
            },
            generated_sql=generation["sql"],
            sql_confidence=generation["confidence"],
            execution_mode="auto_run" if auto_run else "preview",
            execution_status=(
                VannaAskExecutionStatus.GENERATED.value
                if generation["sql"]
                else VannaAskExecutionStatus.FAILED.value
            ),
            execution_result_json={},
            create_user_id=int(owner_user_id),
            create_user_name=create_user_name,
        )
        self.db.add(ask_run)
        self.db.flush()

        execution_result: dict[str, Any] = {}
        auto_train_entry_id: int | None = None
        if auto_run and generation["sql"]:
            execution_result = await self._execute_sql(
                datasource_id=int(datasource_id),
                owner_user_id=int(owner_user_id),
                sql=generation["sql"],
                task_id=task_id,
            )
            self._apply_execution_status(
                ask_run=ask_run,
                execution_result=execution_result,
            )

        if auto_train_on_success and self._should_auto_train(
            generated_sql=generation["sql"],
            execution_status=ask_run.execution_status,
        ):
            # 自动回流只落候选态，不直接发布，避免错误 SQL 立刻污染主检索语料。
            auto_train_entry = self.train_service.train_question_sql(
                datasource_id=int(datasource_id),
                owner_user_id=int(owner_user_id),
                create_user_name=create_user_name,
                question=normalized_question,
                sql=generation["sql"],
                publish=False,
                sql_explanation=generation.get("notes"),
            )
            ask_run.auto_train_entry_id = int(auto_train_entry.id)
            auto_train_entry_id = int(auto_train_entry.id)

        kb.last_ask_at = datetime.now(UTC).replace(tzinfo=None)
        if getattr(kb, "llm_model", None) in {None, ""} and generation.get("model_name"):
            kb.llm_model = generation["model_name"]
        self.db.commit()
        self.db.refresh(ask_run)

        return AskResult(
            ask_run_id=int(ask_run.id),
            execution_status=str(ask_run.execution_status),
            generated_sql=ask_run.generated_sql,
            sql_confidence=ask_run.sql_confidence,
            execution_result=execution_result,
            auto_train_entry_id=auto_train_entry_id,
        )

    def _resolve_kb(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        kb_id: int | None,
    ) -> VannaKnowledgeBase:
        """解析本次 ask 实际使用的知识库。

        这里约定：
        - 显式传 `kb_id` 时，尊重调用方指定知识库
        - 未指定时，按 datasource 懒创建默认知识库

        这样既支持高级调用方精确控制，也保证普通入口不需要先显式建库。
        """

        if kb_id is not None:
            return self.kb_service.get_kb(
                kb_id=int(kb_id),
                owner_user_id=owner_user_id,
            )
        return self.kb_service.get_or_create_default_kb(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            owner_user_name=create_user_name,
        )

    async def _generate_sql(
        self,
        *,
        kb: VannaKnowledgeBase,
        owner_user_id: int,
        question: str,
        prompt_bundle: dict[str, Any],
        retrieval: RetrievalResult,
    ) -> dict[str, Any]:
        """统一封装 SQL 生成。

        支持两类调用方式：
        - 测试/注入场景：直接传入 `llm_callable`
        - 线上默认：通过 `llm_resolver` 取得宿主默认模型
        """

        if self.llm_callable is not None:
            raw = await self._call_maybe_async(
                self.llm_callable,
                messages=prompt_bundle["messages"],
                system_prompt=prompt_bundle["system_prompt"],
                user_prompt=prompt_bundle["user_prompt"],
                kb=kb,
                question=question,
                retrieval=retrieval,
            )
            parsed = self._parse_generation_result(raw)
            parsed["model_name"] = None
            return parsed

        llm = self.llm_resolver(int(owner_user_id)) if self.llm_resolver else None
        if llm is None:
            raise VannaGenerationError("No default chat model is configured")

        # 线上默认强制要求 JSON，尽量把模型输出收敛到稳定契约，减少解析分支。
        raw = await llm.chat(
            prompt_bundle["messages"],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_generation_result(raw)
        parsed["model_name"] = getattr(llm, "model_name", None)
        return parsed

    async def _maybe_load_live_schema_context(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        question: str,
        retrieval: RetrievalResult,
    ) -> dict[str, Any] | None:
        """必要时回退到实时 schema。

        当检索结果几乎没有可用上下文时，再去源库拿 schema，
        这样既减少无意义数据库访问，也能给冷启动场景兜底。
        """

        if not self._should_fallback_to_live_schema(retrieval):
            return None
        try:
            return await self._load_live_schema_context(
                datasource_id=datasource_id,
                owner_user_id=owner_user_id,
                question=question,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load live schema context for datasource %s: %s",
                datasource_id,
                exc,
            )
            return None

    def _should_fallback_to_live_schema(self, retrieval: RetrievalResult) -> bool:
        """判断是否需要回退实时 schema。

        当前策略较保守：只有三类检索结果全空时才命中。
        这样做的原因是实时拉库开销大，而且会把 Prompt 变长；
        一旦已有离线整理过的知识，优先相信离线知识而不是每次都连源库。
        """

        return not (
            retrieval.sql_hits or retrieval.schema_hits or retrieval.doc_hits
        )

    async def _load_live_schema_context(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        question: str,
    ) -> dict[str, Any] | None:
        """从数据源实时抓 schema，并整理成 Prompt 可读文本。

        这是冷启动兜底路径，不负责做持久化 schema 采集；真正的结构入库由
        `SchemaHarvestService` 负责，这里只拿一次瞬时快照给模型补上下文。
        """

        if self.schema_loader is not None:
            schema_snapshot = await self._call_maybe_async(
                self.schema_loader,
                datasource_id=datasource_id,
                owner_user_id=owner_user_id,
                question=question,
            )
        else:
            datasource = self._get_datasource(
                datasource_id=datasource_id,
                owner_user_id=owner_user_id,
            )
            config = database_connection_config_from_url(
                make_url(datasource.url),
                read_only=datasource.read_only,
            )
            adapter = create_adapter_for_type(datasource.type.value, config)
            await adapter.connect()
            try:
                schema_snapshot = await adapter.get_schema()
            finally:
                await adapter.disconnect()
        return self._build_live_schema_context(
            question=question,
            schema_snapshot=schema_snapshot,
        )

    def _build_live_schema_context(
        self,
        *,
        question: str,
        schema_snapshot: Any,
    ) -> dict[str, Any] | None:
        """把数据库 adapter 返回的 schema 快照转成 Prompt 上下文块。"""

        if not isinstance(schema_snapshot, dict):
            return None

        tables = [
            table
            for table in list(schema_snapshot.get("tables") or [])
            if isinstance(table, dict) and str(table.get("table") or "").strip()
        ]
        if not tables:
            return None

        selected_tables = self._select_live_schema_tables(
            question=question,
            tables=tables,
        )
        rendered_tables: list[str] = []
        selected_table_names: list[str] = []
        total_chars = 0
        max_chars = 12000

        for table in selected_tables:
            rendered = self._render_live_schema_table(table)
            if rendered_tables and total_chars + len(rendered) > max_chars:
                break
            rendered_tables.append(rendered)
            selected_table_names.append(self._qualified_table_name(table))
            total_chars += len(rendered)

        if not rendered_tables:
            return None

        return {
            "source": "datasource_live_schema",
            "database_type": (
                schema_snapshot.get("databaseType")
                or schema_snapshot.get("database_type")
            ),
            "family": schema_snapshot.get("family"),
            "table_count": len(tables),
            "selected_table_names": selected_table_names,
            "text": "\n\n".join(rendered_tables),
        }

    def _select_live_schema_tables(
        self,
        *,
        question: str,
        tables: list[dict[str, Any]],
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """按问题相关度选出最值得放进 Prompt 的表。

        排序不是只看表名命中，还会把字段名、注释等都纳入候选 token。
        这样即便用户提的是指标或业务术语，也有机会映射到正确表。
        """

        if not tables:
            return []

        query_tokens = self._tokenize_schema_text(question)
        ranked: list[tuple[float, str, str, dict[str, Any]]] = []

        for table in tables:
            schema_name = str(table.get("schema") or "")
            table_name = str(table.get("table") or "")
            candidate_parts = [
                schema_name,
                table_name,
                str(table.get("comment") or ""),
            ]
            for column in list(table.get("columns") or []):
                if not isinstance(column, dict):
                    continue
                candidate_parts.append(str(column.get("name") or ""))
                candidate_parts.append(str(column.get("comment") or ""))
            candidate_tokens = self._tokenize_schema_text(" ".join(candidate_parts))
            overlap = query_tokens & candidate_tokens
            coverage = len(overlap) / max(1, len(query_tokens)) if query_tokens else 0.0
            richness = min(0.2, len(candidate_tokens) / 200)
            ranked.append((coverage + richness, schema_name, table_name, table))

        ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
        positive = [item[3] for item in ranked if item[0] > 0.2]
        if positive:
            return positive[:limit]
        return [item[3] for item in ranked[:limit]]

    def _render_live_schema_table(self, table: dict[str, Any]) -> str:
        """把单表 schema 渲染成大模型易读文本。"""

        qualified_name = self._qualified_table_name(table)
        lines = [f"表 {qualified_name}"]
        table_comment = self._strip_or_none(table.get("comment"))
        if table_comment:
            lines.append(f"说明: {table_comment}")
        lines.append("DDL:")
        lines.append(
            self._strip_or_none(table.get("ddl"))
            or self._build_synthetic_ddl(table)
        )
        return "\n".join(lines)

    def _build_synthetic_ddl(
        self,
        table: dict[str, Any],
        *,
        max_columns: int = 40,
        max_foreign_keys: int = 12,
    ) -> str:
        """当源库没直接给 DDL 时，用字段信息拼一份近似 DDL。

        这份 DDL 的目标是“给模型读”，不是数据库可 100% 回放的精确建表语句，
        所以这里优先保留字段、主键、外键等推理最关键的信息。
        """

        column_defs: list[str] = []
        columns = [
            column
            for column in list(table.get("columns") or [])
            if isinstance(column, dict) and str(column.get("name") or "").strip()
        ]
        for column in columns[:max_columns]:
            column_name = str(column.get("name") or "").strip()
            data_type = str(column.get("type") or "text").strip()
            nullable = column.get("nullable")
            default_value = column.get("default")
            line = f"  {column_name} {data_type}"
            if nullable is False:
                line += " NOT NULL"
            if default_value not in (None, ""):
                line += f" DEFAULT {default_value}"
            column_comment = self._strip_or_none(column.get("comment"))
            if column_comment:
                line += f" -- {column_comment}"
            column_defs.append(line)

        remaining_columns = len(columns) - len(column_defs)
        if remaining_columns > 0:
            column_defs.append(f"  -- 其余 {remaining_columns} 个字段已省略")

        primary_keys = [
            str(value).strip()
            for value in list(table.get("primary_keys") or [])
            if str(value).strip()
        ]
        if primary_keys:
            column_defs.append(f"  PRIMARY KEY ({', '.join(primary_keys)})")

        foreign_keys = [
            item
            for item in list(table.get("foreign_keys") or [])
            if isinstance(item, dict)
        ]
        for foreign_key in foreign_keys[:max_foreign_keys]:
            constrained = ", ".join(
                str(value).strip()
                for value in list(foreign_key.get("constrained_columns") or [])
                if str(value).strip()
            )
            referred_table = str(foreign_key.get("referred_table") or "").strip()
            referred_columns = ", ".join(
                str(value).strip()
                for value in list(foreign_key.get("referred_columns") or [])
                if str(value).strip()
            )
            if constrained and referred_table and referred_columns:
                column_defs.append(
                    "  FOREIGN KEY "
                    f"({constrained}) REFERENCES {referred_table} ({referred_columns})"
                )

        table_body = ",\n".join(column_defs) if column_defs else "  -- no columns"
        return f"CREATE TABLE {self._qualified_table_name(table)} (\n{table_body}\n);"

    def _qualified_table_name(self, table: dict[str, Any]) -> str:
        schema_name = str(table.get("schema") or "").strip()
        table_name = str(table.get("table") or "").strip()
        return f"{schema_name}.{table_name}" if schema_name else table_name

    def _tokenize_schema_text(self, text: str) -> set[str]:
        normalized = str(text or "").lower()
        tokens: set[str] = set()
        for match in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized):
            if not match:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                tokens.update({char for char in match if char.strip()})
                if len(match) > 1:
                    tokens.update(match[idx : idx + 2] for idx in range(len(match) - 1))
            else:
                tokens.add(match)
        return {token for token in tokens if token}

    def _get_datasource(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
    ) -> Text2SQLDatabase:
        """读取并校验数据源归属。"""

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

    async def _execute_sql(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        sql: str,
        task_id: int | None,
    ) -> dict[str, Any]:
        """执行生成的 SQL。

        当前阶段不保留审批逻辑，但仍然保留统一执行出口，
        方便后续恢复策略控制或注入测试替身。
        """

        datasource = self._get_datasource(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
        )

        if self.sql_executor is not None:
            return await self._call_maybe_async(
                self.sql_executor,
                datasource=datasource,
                sql=sql,
                task_id=task_id,
                user_id=owner_user_id,
            )

        config = database_connection_config_from_url(
            make_url(datasource.url),
            read_only=datasource.read_only,
        )
        adapter = create_adapter_for_type(datasource.type.value, config)
        await adapter.connect()
        try:
            result = await adapter.execute_query(sql)
        finally:
            await adapter.disconnect()

        columns = list(result.rows[0].keys()) if result.rows else []
        return {
            "success": True,
            "rows": result.rows,
            "row_count": (
                result.affected_rows
                if result.affected_rows is not None
                else len(result.rows)
            ),
            "columns": columns,
            "message": "SQL executed successfully",
            "metadata": result.metadata or {},
        }

    def _apply_execution_status(
        self,
        *,
        ask_run: VannaAskRun,
        execution_result: dict[str, Any],
    ) -> None:
        """把执行结果投影成 ask_run 的状态字段。

        当前分支虽然弱化了审批流程，但底层状态位仍保留 `WAITING_APPROVAL`
        等兼容值，目的是兼容历史数据结构与未来策略收紧时的扩展点。
        """

        ask_run.execution_result_json = execution_result
        decision = str(execution_result.get("decision") or "")
        blocked = bool(execution_result.get("blocked"))
        if decision == "wait_approval" or blocked:
            ask_run.execution_status = VannaAskExecutionStatus.WAITING_APPROVAL.value
            ask_run.approval_status = "pending"
            return
        if bool(execution_result.get("success")):
            ask_run.execution_status = VannaAskExecutionStatus.EXECUTED.value
            ask_run.approval_status = "approved"
            return
        ask_run.execution_status = VannaAskExecutionStatus.FAILED.value
        ask_run.approval_status = "rejected" if decision == "deny" else None

    def _should_auto_train(
        self, *, generated_sql: str | None, execution_status: str
    ) -> bool:
        """判断是否允许把 ask 结果自动沉淀成候选训练条目。"""

        if not generated_sql or not generated_sql.strip():
            return False
        return execution_status in {
            VannaAskExecutionStatus.GENERATED.value,
            VannaAskExecutionStatus.EXECUTED.value,
        }

    async def _call_maybe_async(self, func: Callable[..., Any], /, **kwargs: Any) -> Any:
        """兼容同步/异步注入函数，便于测试与扩展。"""

        result = func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _parse_generation_result(self, raw: Any) -> dict[str, Any]:
        """尽量宽松地解析 LLM 返回。

        优先按 JSON 结果解析，失败后再尝试从 markdown/code block 中抽 SQL。
        这样能兼容不同模型、不同 prompt 模板下的返回差异。
        """

        if isinstance(raw, dict) and "sql" in raw:
            return {
                "sql": self._strip_or_none(raw.get("sql")),
                "confidence": self._normalize_confidence(raw.get("confidence")),
                "notes": self._strip_or_none(raw.get("notes")),
            }

        if isinstance(raw, dict) and "content" in raw:
            raw = raw.get("content")

        content = self._strip_or_none(raw)
        if content is None:
            raise VannaGenerationError("LLM returned empty response")

        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match is not None:
            try:
                payload = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return {
                    "sql": self._strip_or_none(payload.get("sql")),
                    "confidence": self._normalize_confidence(payload.get("confidence")),
                    "notes": self._strip_or_none(payload.get("notes")),
                }

        # 有些模型仍可能返回 markdown 或自然语言包裹的 SQL，这里做最后兜底，
        # 避免因为格式不完美而把本来可用的结果整条丢弃。
        sql = self._extract_sql_from_text(content)
        if sql is None:
            raise VannaGenerationError("Failed to parse SQL from LLM response")
        return {"sql": sql, "confidence": None, "notes": None}

    def _extract_sql_from_text(self, content: str) -> str | None:
        """从纯文本里兜底提取 SQL。"""

        code_block = re.search(r"```(?:sql)?\s*([\s\S]*?)```", content, re.IGNORECASE)
        if code_block is not None:
            return self._strip_or_none(code_block.group(1))

        upper = content.upper()
        for keyword in ("SELECT ", "WITH "):
            idx = upper.find(keyword)
            if idx >= 0:
                return self._strip_or_none(content[idx:])
        return None

    def _normalize_confidence(self, value: Any) -> float | None:
        """把模型置信度规范到 0~1。"""

        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, numeric))

    def _strip_or_none(self, value: Any) -> str | None:
        """统一做字符串清洗。"""

        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None
