"""Prompt builder for SQL Brain."""

from __future__ import annotations

from .models import SqlGenerationContext


def build_sql_prompt(context: SqlGenerationContext) -> str:
    """Build a SQL-focused prompt from retrieved context.

    设计原则：
    - 只放相关上下文
    - 明确数据库类型和输出约束
    - 不直接耦合 LLM SDK
    """
    question_sql_section = (
        "\n\n".join(
            f"问题：{item.question}\nSQL：{item.sql}"
            for item in context.question_sql_examples
        )
        if context.question_sql_examples
        else "无相关历史 SQL 示例"
    )

    ddl_section = (
        "\n\n".join(
            f"表：{item.table_name}\nDDL：{item.ddl}" for item in context.ddl_snippets
        )
        if context.ddl_snippets
        else "无相关 DDL"
    )

    documentation_section = (
        "\n\n".join(item.content for item in context.documentation_chunks)
        if context.documentation_chunks
        else "无相关业务文档"
    )

    db_type = context.db_type or "unknown"
    system_short = context.system_short or "unknown"

    return f"""
你是一个专业的 SQL 生成助手。

【用户问题】
{context.question}

【数据库信息】
- db_type: {db_type}
- system_short: {system_short}

【相关 DDL】
{ddl_section}

【相关历史 SQL】
{question_sql_section}

【相关业务文档】
{documentation_section}

【输出约束】
1. 只基于给定上下文生成 SQL
2. 如果信息不足，可以先生成中间探查 SQL
3. 最终输出必须是 SQL 或结构化中间探查请求
4. 尽量复用与相关历史 SQL 一致的 join、过滤和字段口径
""".strip()
