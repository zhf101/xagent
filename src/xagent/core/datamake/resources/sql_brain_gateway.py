"""
`Resource Plane / SQL Brain Gateway`（资源平面 / SQL Brain 网关）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`（资源平面）
- 在你的设计里：SQL 能力核门面，不是主脑

这个文件负责什么：
- 对外提供 SQL Brain Phase 1 的统一入口
- 组织 generate / verify / probe / repair 四类技术能力
- 把 LLM、schema、verifier 这些底层实现细节藏在受控门面后面

这个文件不负责什么：
- 不决定当前任务最值得做什么
- 不审批、不放行、不创建工单
- 不直接替代 Guard / Runtime
- 不把 SQL Brain 做成新的 Agent 或新的工作流引擎

设计边界：
- `SqlBrainGateway`（SQL Brain 网关）只回答“SQL 技术上怎么更稳地做”
- `Agent` 仍然决定“要不要做”
- `Guard` 仍然决定“能不能做”
- `Runtime` 仍然决定“怎样稳定做完”
"""

from __future__ import annotations

import json
import re
from typing import Any

from json_repair import loads as repair_loads

from ...model.chat.basic.base import BaseLLM
from ..contracts.sql_plan import (
    SqlPlanContext,
    SqlPlanResult,
    SqlProbeResult,
    SqlProbeTarget,
    SqlRepairResult,
    SqlVerificationResult,
)
from ..guard.sql_verifier import SqlVerifier
from .openviking_sql_context_provider import OpenVikingSqlContextProvider
from .sql_context_provider import CompositeSqlContextProvider
from .sql_datasource_resolver import SqlDatasourceResolver
from .sql_schema_provider import SqlSchemaProvider

SQL_CONTEXT_PREPARED_FLAG = "_system_sql_context_prepared"
SQL_CONTEXT_PREPARED_PROVIDERS = "_system_sql_context_providers"


class SqlBrainGateway:
    """
    `SqlBrainGateway`（SQL Brain 网关）。

    Phase 1 的目标不是“做一个新的 SQL Agent”，
    而是先把 SQL 技术能力沉到 datamake 五层架构里，形成稳定可接线的能力门面。
    """

    def __init__(
        self,
        *,
        llm: BaseLLM | None = None,
        schema_provider: SqlSchemaProvider | None = None,
        datasource_resolver: SqlDatasourceResolver | None = None,
        context_provider: CompositeSqlContextProvider | None = None,
        verifier: SqlVerifier | None = None,
    ) -> None:
        self.llm = llm
        self.datasource_resolver = datasource_resolver or SqlDatasourceResolver()
        self.schema_provider = schema_provider or SqlSchemaProvider(self.datasource_resolver)
        self.context_provider = context_provider or CompositeSqlContextProvider(
            [OpenVikingSqlContextProvider()]
        )
        self.verifier = verifier or SqlVerifier()

    async def prepare_context(self, context: SqlPlanContext) -> SqlPlanContext:
        """
        准备 SQL Brain 实际消费的上下文。

        顺序原则：
        1. 先保留显式上下文
        2. 再由外部 provider 做补充
        3. provider 只能补充，不能越权改写业务决策

        幂等要求：
        - Guard / Runtime 可能都会先显式调用一次 `prepare_context()`
        - 而 `generate_plan()` / `repair_plan()` 内部也会再次兜底调用
        - 因此这里必须做幂等保护，避免 OpenViking 之类的外部 provider
          在同一轮里被重复请求两次
        """

        if context.metadata.get(SQL_CONTEXT_PREPARED_FLAG) is True:
            return context

        enriched = await self.context_provider.enrich(context)
        provider_names = [
            getattr(provider, "name", type(provider).__name__)
            for provider in self.context_provider.providers
        ]
        metadata = dict(enriched.metadata)
        metadata[SQL_CONTEXT_PREPARED_FLAG] = True
        metadata[SQL_CONTEXT_PREPARED_PROVIDERS] = provider_names
        return enriched.model_copy(update={"metadata": metadata})

    async def generate_plan(self, context: SqlPlanContext) -> SqlPlanResult:
        """
        生成或继承一份 SQL 草案。

        生成策略：
        - 上游已经给了 `draft_sql`，优先沿用草稿
        - 没有草稿且没有 LLM，则返回结构化失败
        - 有 LLM 时，基于 schema / 示例 / 文档生成一条候选 SQL
        """

        effective_context = await self.prepare_context(context)
        schema_ddl = self._resolve_schema_ddl(effective_context)
        if effective_context.draft_sql and effective_context.draft_sql.strip():
            return SqlPlanResult(
                success=True,
                sql=effective_context.draft_sql.strip(),
                reasoning="沿用上游已经形成的 SQL 草稿，当前阶段不重复改写。",
                source="draft",
                metadata=self._build_common_metadata(
                    context=effective_context,
                    schema_ddl=schema_ddl,
                ),
            )

        if self.llm is None:
            return SqlPlanResult(
                success=False,
                sql=None,
                reasoning="当前未配置 SQL 生成模型，无法从自然语言直接生成 SQL。",
                source="empty",
                issues=["missing_sql_brain_llm"],
                metadata=self._build_common_metadata(
                    context=effective_context,
                    schema_ddl=schema_ddl,
                ),
            )

        prompt = self._build_generate_prompt(
            context=effective_context,
            schema_ddl=schema_ddl,
        )
        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        payload = self._parse_llm_json_response(response)

        sql = self._extract_non_empty_string(payload.get("sql"))
        reasoning = self._extract_non_empty_string(payload.get("reasoning"))
        issues = [] if sql else ["llm_returned_empty_sql"]

        return SqlPlanResult(
            success=bool(sql),
            sql=sql,
            reasoning=reasoning or "已根据问题、schema 与示例尝试生成 SQL 草案。",
            source="llm" if sql else "empty",
            issues=issues,
            metadata={
                **self._build_common_metadata(
                    context=effective_context,
                    schema_ddl=schema_ddl,
                ),
                "llm_model": getattr(self.llm, "model_name", None),
            },
        )

    def verify_plan(
        self,
        *,
        sql: str,
        context: SqlPlanContext,
    ) -> SqlVerificationResult:
        """
        对 SQL 草案做静态校验。
        """

        return self.verifier.verify(
            sql,
            db_type=context.db_type,
            read_only=context.read_only,
            schema_ddl=self._resolve_schema_ddl(context),
        )

    def probe_plan(
        self,
        *,
        sql: str,
        context: SqlPlanContext,
        target: SqlProbeTarget | None = None,
    ) -> SqlProbeResult:
        """
        对 SQL 草案做无副作用探测。

        Phase 1 刻意保守：
        - 先以静态校验作为 probe 主体
        - 最多生成一个“预检预览 SQL”，但不直接连接数据库执行
        - 真正是否进入 Runtime execute，仍由 Guard / Runtime 决定
        """

        verification = self.verify_plan(sql=sql, context=context)
        effective_target = target or SqlProbeTarget(
            connection_name=context.connection_name,
            db_url=context.db_url,
            db_type=context.db_type,
            read_only=context.read_only,
            source="plan_context",
        )

        if not verification.valid:
            return SqlProbeResult(
                ok=False,
                mode="static_only",
                summary="SQL 静态校验未通过，探测阶段已阻断。",
                error="static_verification_failed",
                metadata={
                    "statement_kind": verification.statement_kind,
                    "risk_level": verification.risk_level,
                    "reasons": list(verification.reasons),
                    "target_source": effective_target.source,
                },
            )

        probe_sql = self._build_probe_sql_preview(sql=sql, verification=verification)
        return SqlProbeResult(
            ok=True,
            mode="preflight_preview" if probe_sql else "static_only",
            summary="SQL 已通过静态探测，可继续进入 Guard / Runtime 后续判定。",
            probe_sql=probe_sql,
            metadata={
                "statement_kind": verification.statement_kind,
                "risk_level": verification.risk_level,
                "target_source": effective_target.source,
                "read_only": effective_target.read_only,
                "connection_name": effective_target.connection_name,
            },
        )

    async def repair_plan(
        self,
        *,
        sql: str,
        context: SqlPlanContext,
        verification: SqlVerificationResult | None = None,
        probe: SqlProbeResult | None = None,
    ) -> SqlRepairResult:
        """
        根据 verify / probe 结果尝试修复 SQL。

        repair 只是提出候选草案，不绕过上游控制边界。
        """

        verification = verification or self.verify_plan(sql=sql, context=context)
        repair_issues = list(verification.reasons)
        if probe is not None and probe.error:
            repair_issues.append(probe.error)

        if not repair_issues:
            return SqlRepairResult(
                repaired_sql=sql,
                changed=False,
                reasoning="当前 SQL 未发现需要修复的静态问题。",
                metadata={"repair_needed": False},
            )

        if self.llm is None:
            fallback_sql = self._rule_based_limit_repair(sql, verification)
            if fallback_sql and fallback_sql != sql:
                return SqlRepairResult(
                    repaired_sql=fallback_sql,
                    changed=True,
                    reasoning="未配置修复模型，已按保守规则自动补充 LIMIT。",
                    metadata={"repair_mode": "rule_based_limit"},
                )
            return SqlRepairResult(
                repaired_sql=None,
                changed=False,
                reasoning="当前未配置修复模型，且规则修复不足以可靠处理该问题。",
                issues=repair_issues,
                metadata={"repair_mode": "unavailable"},
            )

        effective_context = await self.prepare_context(context)
        schema_ddl = self._resolve_schema_ddl(effective_context)
        prompt = self._build_repair_prompt(
            context=effective_context,
            sql=sql,
            schema_ddl=schema_ddl,
            verification=verification,
            probe=probe,
        )
        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        payload = self._parse_llm_json_response(response)
        repaired_sql = self._extract_non_empty_string(payload.get("sql"))
        reasoning = self._extract_non_empty_string(payload.get("reasoning"))

        return SqlRepairResult(
            repaired_sql=repaired_sql,
            changed=bool(repaired_sql and repaired_sql.strip() != sql.strip()),
            reasoning=reasoning or "已根据静态校验结果尝试修复 SQL。",
            issues=[] if repaired_sql else repair_issues,
            metadata={
                "repair_mode": "llm",
                "llm_model": getattr(self.llm, "model_name", None),
            },
        )

    def _resolve_schema_ddl(self, context: SqlPlanContext) -> list[str]:
        """
        统一解析当前上下文可见的 schema DDL。
        """

        if context.schema_ddl:
            return list(context.schema_ddl)
        return self.schema_provider.resolve_schema_ddl(
            metadata=context.metadata,
            params={
                "connection_name": context.connection_name,
                "db_url": context.db_url,
            },
        )

    def _build_common_metadata(
        self,
        *,
        context: SqlPlanContext,
        schema_ddl: list[str],
    ) -> dict[str, Any]:
        """
        构建 generate / verify / repair 都可复用的元数据。
        """

        return {
            "resource_key": context.resource_key,
            "operation_key": context.operation_key,
            "db_type": context.db_type,
            "read_only": context.read_only,
            "schema_count": len(schema_ddl),
            "example_count": len(context.example_sqls),
            "documentation_count": len(context.documentation_snippets),
        }

    def _build_generate_prompt(
        self,
        *,
        context: SqlPlanContext,
        schema_ddl: list[str],
    ) -> str:
        """
        生成 SQL 草案提示词。
        """

        examples = "\n\n".join(f"- {item}" for item in context.example_sqls[:5]) or "- 无"
        documents = "\n\n".join(f"- {item}" for item in context.documentation_snippets[:5]) or "- 无"
        schema_text = "\n\n".join(schema_ddl[:12]) or "-- 无可用 schema"
        return (
            "你是受控 SQL 规划助手，不是任务主脑。\n"
            "只返回 JSON，不要输出 Markdown。\n"
            "请根据问题、schema 与示例，生成一条最保守、最可验证的 SQL。\n\n"
            f"问题：{context.question}\n"
            f"数据库类型：{context.db_type or 'unknown'}\n"
            f"只读模式：{context.read_only}\n\n"
            f"示例 SQL：\n{examples}\n\n"
            f"补充文档：\n{documents}\n\n"
            f"Schema DDL：\n{schema_text}\n\n"
            "输出 JSON 结构："
            '{"sql": "string|null", "reasoning": "string"}'
        )

    def _build_repair_prompt(
        self,
        *,
        context: SqlPlanContext,
        sql: str,
        schema_ddl: list[str],
        verification: SqlVerificationResult,
        probe: SqlProbeResult | None,
    ) -> str:
        """
        生成 SQL 修复提示词。
        """

        schema_text = "\n\n".join(schema_ddl[:12]) or "-- 无可用 schema"
        probe_text = json.dumps(
            probe.model_dump(mode="json") if probe is not None else {},
            ensure_ascii=False,
            indent=2,
        )
        verification_text = json.dumps(
            verification.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        return (
            "你是受控 SQL 修复助手，不是审批器，也不是任务主脑。\n"
            "请只根据给定问题、SQL、静态校验结果和 schema 修复 SQL。\n"
            "如果无法可靠修复，请把 sql 设为 null。\n"
            "只返回 JSON，不要输出 Markdown。\n\n"
            f"问题：{context.question}\n"
            f"数据库类型：{context.db_type or 'unknown'}\n"
            f"只读模式：{context.read_only}\n\n"
            f"原始 SQL：\n{sql}\n\n"
            f"静态校验结果：\n{verification_text}\n\n"
            f"探测结果：\n{probe_text}\n\n"
            f"Schema DDL：\n{schema_text}\n\n"
            "输出 JSON 结构："
            '{"sql": "string|null", "reasoning": "string"}'
        )

    def _parse_llm_json_response(self, response: str | dict[str, Any]) -> dict[str, Any]:
        """
        把 LLM 返回统一解析成 JSON 对象。
        """

        if isinstance(response, dict):
            if "content" in response and isinstance(response["content"], str):
                raw_text = response["content"]
            else:
                return response
        else:
            raw_text = response

        try:
            repaired = repair_loads(raw_text)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

        json_match = re.search(r"\{[\s\S]*\}", raw_text)
        if json_match is not None:
            try:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        return {}

    def _build_probe_sql_preview(
        self,
        *,
        sql: str,
        verification: SqlVerificationResult,
    ) -> str | None:
        """
        为只读查询生成一个“预检预览 SQL”。

        注意这里只生成预览文本，不负责执行。
        """

        if verification.is_write:
            return None
        if verification.statement_kind != "select":
            return None
        normalized = sql.strip().rstrip(";")
        return f"SELECT * FROM ({normalized}) AS xagent_probe_preview LIMIT 0"

    def _rule_based_limit_repair(
        self,
        sql: str,
        verification: SqlVerificationResult,
    ) -> str | None:
        """
        Phase 1 的最小规则修复：
        - 只对普通无 LIMIT 的只读 SELECT 自动补 LIMIT
        """

        if verification.statement_kind != "select":
            return None
        if verification.has_limit:
            return None
        if verification.is_write:
            return None
        return sql.strip().rstrip(";") + " LIMIT 100"

    def _extract_non_empty_string(self, value: Any) -> str | None:
        """
        取非空字符串，避免下游到处做空值清洗。
        """

        if isinstance(value, str) and value.strip():
            return value.strip()
        return None
