"""SQL generation and intermediate SQL probing."""

from __future__ import annotations

from .models import SqlGenerationContext, SqlGenerationResult


class SqlBrainGenerator:
    """Minimal SQL generator with intermediate SQL protocol.

    当前阶段先不直接绑定真实 LLM 服务，先把：
    - SQL 结果对象
    - intermediate SQL 探查协议
    跑通，后续 Task7 再接 verifier / repair，之后再接真实模型。
    """

    def generate(self, context: SqlGenerationContext) -> SqlGenerationResult:
        if not context.ddl_snippets:
            return SqlGenerationResult(
                intermediate_sql="SELECT table_name FROM information_schema.tables LIMIT 20;",
                reasoning="缺少相关 DDL，上下文不足，先探查可用表结构。",
                needs_schema_introspection=True,
            )

        # 优先复用历史 SQL 示例
        if context.question_sql_examples:
            return SqlGenerationResult(
                sql=context.question_sql_examples[0].sql,
                reasoning="已复用最相关历史 SQL 作为首选候选。",
            )

        # 最小规则化 fallback：只为常见 count/count by time 问题生成 SQL
        table_name = context.ddl_snippets[0].table_name
        if "新增" in context.question and "用户" in context.question:
            db_type = (context.db_type or "").lower()
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
                reasoning="根据问题语义和数据库方言生成了最小统计 SQL。",
            )

        return SqlGenerationResult(
            intermediate_sql=f"SELECT * FROM {table_name} LIMIT 5;",
            reasoning="当前问题无法直接稳定生成最终 SQL，先探查表样本数据。",
            needs_schema_introspection=True,
        )
