"""Vanna ask 主链路服务。"""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ...core.database.adapters import create_adapter_for_type
from ...core.database.config import database_connection_config_from_url
from ...web.models.text2sql import Text2SQLDatabase
from ...web.models.vanna import (
    VannaAskExecutionStatus,
    VannaAskRun,
    VannaKnowledgeBase,
)
from ...web.services.model_service import get_default_model
from .contracts import AskResult, RetrievalResult
from .errors import VannaDatasourceNotFoundError, VannaGenerationError
from .knowledge_base_service import KnowledgeBaseService
from .prompt_builder import PromptBuilder
from .retrieval_service import RetrievalService
from .train_service import TrainService


class AskService:
    """负责召回、组 Prompt、生成 SQL、可选执行与候选回流。"""

    def __init__(
        self,
        db: Session,
        *,
        retrieval_service: RetrievalService | None = None,
        prompt_builder: PromptBuilder | None = None,
        llm_callable: Callable[..., Any] | None = None,
        llm_resolver: Callable[[int | None], Any] | None = None,
        sql_executor: Callable[..., Any] | None = None,
        train_service: TrainService | None = None,
    ) -> None:
        self.db = db
        self.kb_service = KnowledgeBaseService(db)
        self.retrieval_service = retrieval_service or RetrievalService(db)
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.llm_callable = llm_callable
        self.llm_resolver = llm_resolver or get_default_model
        self.sql_executor = sql_executor
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
        """执行 ask。"""
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
        prompt_bundle = self.prompt_builder.build_prompt(
            kb=kb,
            question=normalized_question,
            retrieval=retrieval,
        )
        generation = await self._generate_sql(
            kb=kb,
            owner_user_id=owner_user_id,
            question=normalized_question,
            prompt_bundle=prompt_bundle,
            retrieval=retrieval,
        )

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

        raw = await llm.chat(
            prompt_bundle["messages"],
            response_format={"type": "json_object"},
        )
        parsed = self._parse_generation_result(raw)
        parsed["model_name"] = getattr(llm, "model_name", None)
        return parsed

    async def _execute_sql(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        sql: str,
        task_id: int | None,
    ) -> dict[str, Any]:
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
        if not generated_sql or not generated_sql.strip():
            return False
        return execution_status in {
            VannaAskExecutionStatus.GENERATED.value,
            VannaAskExecutionStatus.EXECUTED.value,
        }

    async def _call_maybe_async(self, func: Callable[..., Any], /, **kwargs: Any) -> Any:
        result = func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _parse_generation_result(self, raw: Any) -> dict[str, Any]:
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

        sql = self._extract_sql_from_text(content)
        if sql is None:
            raise VannaGenerationError("Failed to parse SQL from LLM response")
        return {"sql": sql, "confidence": None, "notes": None}

    def _extract_sql_from_text(self, content: str) -> str | None:
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
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, numeric))

    def _strip_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None
