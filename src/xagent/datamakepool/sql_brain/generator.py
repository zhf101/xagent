"""SQL 生成器。

当前目标不是一步做到“最强”，而是把链路从占位实现升级为可工作的最小版本：
- 优先走真实 LLM
- 无 LLM 时允许降级，但不再无条件复用第一条历史 SQL
- 保留 intermediate SQL 协议，支持后续二次生成闭环
"""

from __future__ import annotations

from xagent.core.model.chat.basic.base import BaseLLM

from .llm_utils import extract_sql_from_text, run_async_sync
from .models import SqlGenerationContext, SqlGenerationResult
from .prompt_builder import build_sql_messages


class SqlBrainGenerator:
    """SQL Brain 生成器。

    设计重点：
    - 有 LLM 时走真实消息 prompt
    - 无 LLM 时只做保守降级，不再“样例一条吃天下”
    """

    def __init__(
        self,
        llm: BaseLLM | None = None,
        *,
        reuse_score_threshold: float = 0.92,
    ):
        self._llm = llm
        self._reuse_score_threshold = reuse_score_threshold

    @property
    def llm_model_name(self) -> str | None:
        return self._llm.model_name if self._llm is not None else None

    def _extract_sql(self, llm_response: str) -> str:
        """从模型响应里提取 SQL。"""

        return extract_sql_from_text(llm_response)

    def _invoke_llm(self, context: SqlGenerationContext) -> SqlGenerationResult | None:
        if self._llm is None:
            return None

        messages = build_sql_messages(context)
        response = run_async_sync(
            self._llm.chat(
                messages=messages,
                temperature=0.0,
            )
        )

        if not isinstance(response, str):
            return SqlGenerationResult(
                intermediate_sql=None,
                reasoning="LLM 返回了非文本结果，已回退到保守生成策略。",
                needs_schema_introspection=not bool(context.ddl_snippets),
            )

        extracted_sql = self._extract_sql(response)
        if "intermediate_sql" in response.lower():
            return SqlGenerationResult(
                intermediate_sql=extracted_sql,
                reasoning=response,
                needs_schema_introspection=True,
            )

        return SqlGenerationResult(
            sql=extracted_sql,
            reasoning=response,
        )

    def _generate_without_llm(
        self,
        context: SqlGenerationContext,
    ) -> SqlGenerationResult:
        """无 LLM 时的保守降级策略。"""

        if not context.ddl_snippets:
            return SqlGenerationResult(
                intermediate_sql="SELECT table_name FROM information_schema.tables LIMIT 20;",
                reasoning="未配置可用 LLM，且缺少相关 DDL，上下文不足，先探查表结构。",
                needs_schema_introspection=True,
            )

        top_example = context.question_sql_examples[0] if context.question_sql_examples else None
        if (
            top_example is not None
            and top_example.score >= self._reuse_score_threshold
            and top_example.question.strip() == context.question.strip()
        ):
            return SqlGenerationResult(
                sql=top_example.sql,
                reasoning="未配置 LLM，但历史问题与当前问题精确命中，复用已验证示例 SQL。",
            )

        table_name = context.ddl_snippets[0].table_name
        normalized_question = context.question.lower()
        db_type = (context.db_type or "").lower()
        if "新增" in context.question and "用户" in context.question:
            if db_type in {"postgresql", "kingbase", "gaussdb", "vastbase", "highgo"}:
                sql = (
                    f"SELECT count(*) AS new_user_count FROM {table_name} "
                    "WHERE created_at >= current_date - interval '7 day';"
                )
            elif db_type in {"mysql", "tidb", "oceanbase", "polardb", "goldendb"}:
                sql = (
                    f"SELECT count(*) AS new_user_count FROM {table_name} "
                    "WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY);"
                )
            else:
                sql = f"SELECT count(*) AS new_user_count FROM {table_name};"
            return SqlGenerationResult(
                sql=sql,
                reasoning="未配置 LLM，按保守规则生成统计 SQL。",
            )

        if "list" in normalized_question or "查询" in context.question or "查看" in context.question:
            return SqlGenerationResult(
                intermediate_sql=f"SELECT * FROM {table_name} LIMIT 5;",
                reasoning="未配置 LLM，先返回最小探查 SQL，避免错误复用无关历史 SQL。",
                needs_schema_introspection=True,
            )

        return SqlGenerationResult(
            intermediate_sql=f"SELECT * FROM {table_name} LIMIT 5;",
            reasoning="当前问题无法在无 LLM 条件下稳定生成最终 SQL，先探查样本数据。",
            needs_schema_introspection=True,
        )

    def generate(self, context: SqlGenerationContext) -> SqlGenerationResult:
        llm_result = self._invoke_llm(context)
        if llm_result is not None:
            return llm_result
        return self._generate_without_llm(context)
