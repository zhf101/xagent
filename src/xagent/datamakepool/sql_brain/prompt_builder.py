"""SQL Brain prompt 构建器。"""

from __future__ import annotations

from .models import SqlGenerationContext


def _build_ddl_section(context: SqlGenerationContext) -> str:
    if not context.ddl_snippets:
        return "无相关 DDL"
    return "\n\n".join(
        f"表：{item.table_name}\nDDL：{item.ddl}" for item in context.ddl_snippets
    )


def _build_question_sql_section(context: SqlGenerationContext) -> str:
    if not context.question_sql_examples:
        return "无相关历史 SQL 示例"
    return "\n\n".join(
        f"问题：{item.question}\nSQL：{item.sql}\n相关度：{item.score:.3f}"
        for item in context.question_sql_examples
    )


def _build_documentation_section(context: SqlGenerationContext) -> str:
    if not context.documentation_chunks:
        return "无相关业务文档"
    return "\n\n".join(
        f"文档片段（相关度：{item.score:.3f}）：\n{item.content}"
        for item in context.documentation_chunks
    )


def build_sql_prompt(context: SqlGenerationContext) -> str:
    """生成便于日志记录和调试的人类可读 prompt。"""

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
{_build_ddl_section(context)}

【相关历史 SQL】
{_build_question_sql_section(context)}

【相关业务文档】
{_build_documentation_section(context)}

【输出约束】
1. 只基于给定上下文生成 SQL。
2. 优先复用历史示例里的 join、过滤和字段口径，但不要机械照抄无关 SQL。
3. 如果上下文不足，请返回一个最小的 intermediate SQL 做进一步探查。
4. 只返回 SQL；如果是中间探查 SQL，请在 SQL 前加一行注释 `-- intermediate_sql`。
5. SQL 必须符合当前 db_type 方言。
""".strip()


def build_sql_messages(context: SqlGenerationContext) -> list[dict[str, str]]:
    """生成真正送给模型的消息列表。

    与之前只拼纯字符串不同，这里把历史 question/sql 示例组织成 few-shot，
    让模型更容易学习已有 SQL 资产的写法和口径。
    """

    system_message = {
        "role": "system",
        "content": build_sql_prompt(context),
    }
    messages: list[dict[str, str]] = [system_message]

    for item in context.question_sql_examples[:3]:
        messages.append({"role": "user", "content": item.question})
        messages.append({"role": "assistant", "content": item.sql})

    messages.append({"role": "user", "content": context.question})
    return messages


def build_sql_repair_prompt(
    context: SqlGenerationContext,
    *,
    failed_sql: str,
    error: str,
) -> str:
    """构造 SQL 修复 prompt。

    修复阶段和首次生成的差异在于：
    - 已知一条失败 SQL
    - 已知数据库或执行层错误
    - 目标不是“重新理解需求”，而是在当前上下文内做最小正确修复
    """

    db_type = context.db_type or "unknown"
    system_short = context.system_short or "unknown"

    return f"""
你是一个专业的 SQL 修复助手。

【用户问题】
{context.question}

【数据库信息】
- db_type: {db_type}
- system_short: {system_short}

【失败 SQL】
{failed_sql}

【错误信息】
{error}

【相关 DDL】
{_build_ddl_section(context)}

【相关历史 SQL】
{_build_question_sql_section(context)}

【相关业务文档】
{_build_documentation_section(context)}

【修复要求】
1. 仅基于给定上下文修复 SQL，不要臆造不存在的表和列。
2. 尽量做最小修改，保留原始查询意图。
3. 若原 SQL 为普通查询，优先保留或补充 LIMIT。
4. 输出只允许是一条 SQL，不要解释，不要 markdown。
""".strip()


def build_sql_repair_messages(
    context: SqlGenerationContext,
    *,
    failed_sql: str,
    error: str,
) -> list[dict[str, str]]:
    """生成修复阶段的消息列表。"""

    return [
        {
            "role": "system",
            "content": build_sql_repair_prompt(
                context,
                failed_sql=failed_sql,
                error=error,
            ),
        }
    ]
