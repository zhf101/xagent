"""
`Core Contracts / SQL Brain Contracts`（核心契约层 / SQL Brain 契约）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/contracts`
- 架构分层：`Core Contracts`（核心契约层）
- 在你的设计里：`Resource Plane`、`Guard Plane`、`Runtime Plane`
  之间共享的 SQL 结构化语言

这个文件负责什么：
- 定义 SQL Brain Phase 1 需要跨层传递的结构化对象
- 让生成（generate）、校验（verify）、探测（probe）、修复（repair）
  都依赖稳定契约，而不是松散字典
- 为后续 ledger / 审批 / UI 展示保留可持续扩展的字段位

这个文件不负责什么：
- 不负责生成 SQL
- 不负责审批判断
- 不负责真正访问数据库
- 不负责决定“下一步业务动作”

设计原因：
- 你前面已经明确强调“唯一控制律（Single Control Law）”，
  所以 SQL Brain 不能越权成另一个主脑。
- 这里的模型只提供“可共享、可审计、可验证”的技术事实，
  让 Agent / Guard / Runtime 在各自边界内工作。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class SqlPlanContext(BaseModel):
    """
    `SqlPlanContext`（SQL 规划上下文）。

    它描述的是“SQL Brain 当前可见的技术上下文”，不是任务全局上下文。
    这样做的目的是把 SQL 生成/校验所需信息收敛成一个小而稳的对象，
    避免把整个 AgentContext、整个账本快照、整个 UI 状态直接灌进 SQL 子模块。
    """

    question: str = Field(description="当前要回答的自然语言问题或执行意图。")
    resource_key: str | None = Field(default=None, description="命中的资源键。")
    operation_key: str | None = Field(default=None, description="命中的资源动作键。")
    connection_name: str | None = Field(
        default=None,
        description="外部数据库连接名，对应 XAGENT_EXTERNAL_DB_<NAME>。",
    )
    db_url: str | None = Field(
        default=None,
        description="直接可用的数据库连接 URL。Phase 1 仅作为底层技术输入，不建议上层广泛暴露。",
    )
    db_type: str | None = Field(
        default=None,
        description="数据库类型，如 postgresql / mysql / sqlite。",
    )
    read_only: bool = Field(
        default=True,
        description="是否只允许只读 SQL。这个字段直接影响 verifier 和 probe 的安全收缩策略。",
    )
    draft_sql: str | None = Field(
        default=None,
        description="当前上游已形成的 SQL 草稿。若存在，gateway 应优先把它视为待验证对象，而不是重新脑补。",
    )
    schema_ddl: list[str] = Field(
        default_factory=list,
        description="当前轮可见的 DDL 片段集合，优先使用显式注入的 schema 快照。",
    )
    example_sqls: list[str] = Field(
        default_factory=list,
        description="few-shot SQL 示例，主要用于生成和修复提示，不参与权限决策。",
    )
    documentation_snippets: list[str] = Field(
        default_factory=list,
        description="补充文档片段，如口径说明、业务定义、字段注释等。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="补充元数据。仅承载技术事实，不承载下一步业务决策。",
    )


class SqlPlanResult(BaseModel):
    """
    `SqlPlanResult`（SQL 规划结果）。

    这是 generate 阶段的输出。
    它表达“当前得到了一份怎样的 SQL 草案”，而不是表达“现在就应该去执行它”。
    """

    success: bool = Field(description="是否成功产出可继续处理的 SQL 草案。")
    sql: str | None = Field(default=None, description="生成或继承得到的 SQL 文本。")
    reasoning: str | None = Field(
        default=None,
        description="面向审计和调试的简要推理说明，不是审批结论。",
    )
    source: Literal["draft", "llm", "empty"] = Field(
        default="empty",
        description="SQL 草案来源：已有草稿 / LLM 生成 / 无结果。",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="生成阶段发现的问题，例如缺 schema、缺示例、LLM 返回不可解析。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="生成阶段附加事实，如模型名、schema 数量、示例数量。",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="结果生成时间。",
    )


class SqlVerificationResult(BaseModel):
    """
    `SqlVerificationResult`（SQL 校验结果）。

    这是 Guard / Probe 可直接消费的静态事实。
    关键边界：
    - 它只回答“这条 SQL 从静态规则上看是否安全、是否合理”
    - 它不回答“因此现在应该执行业务动作 A 还是 B”
    """

    valid: bool = Field(description="是否通过当前静态校验。")
    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        default="low",
        description="当前 SQL 的静态风险等级。",
    )
    statement_kind: str = Field(
        default="unknown",
        description="语句类型，如 select / insert / update / delete / ddl。",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="未通过或需要注意的原因列表。",
    )
    detected_tables: list[str] = Field(
        default_factory=list,
        description="从 SQL 中静态识别出的表名。",
    )
    detected_columns: list[str] = Field(
        default_factory=list,
        description="从 SQL 中静态识别出的列引用。",
    )
    has_limit: bool = Field(
        default=False,
        description="对普通查询是否显式带 LIMIT。主要用于控制扫表风险。",
    )
    is_write: bool = Field(
        default=False,
        description="是否属于写 SQL 或 DDL / DML 类高风险语句。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="静态校验过程中的补充事实。",
    )


class SqlProbeTarget(BaseModel):
    """
    `SqlProbeTarget`（SQL 探测目标）。

    这个对象只描述“如果要做技术探测，应该连到哪里”。
    它不隐含审批通过，也不等于正式执行授权。
    """

    connection_name: str | None = Field(
        default=None,
        description="外部数据库连接名，优先用于运行时按环境变量取真实连接。",
    )
    db_url: str | None = Field(
        default=None,
        description="显式数据库连接串。Phase 1 允许存在，但更推荐上游传 connection_name。",
    )
    db_type: str | None = Field(default=None, description="数据库类型。")
    read_only: bool = Field(
        default=True,
        description="探测是否必须处于只读模式。默认必须为 True。",
    )
    source: str | None = Field(
        default=None,
        description="探测目标来源，例如 resource_metadata / datasource_asset / runtime_injected。",
    )


class SqlProbeResult(BaseModel):
    """
    `SqlProbeResult`（SQL 探测结果）。

    这里记录的是“进入正式执行前的技术可行性判断”，
    而不是最终业务执行结果。
    """

    ok: bool = Field(description="是否通过当前探测。")
    mode: Literal["static_only", "preflight_preview"] = Field(
        default="static_only",
        description="探测模式。Phase 1 先保守实现无副作用静态探测。",
    )
    summary: str = Field(default="", description="探测摘要。")
    error: str | None = Field(default=None, description="探测失败时的错误概述。")
    probe_sql: str | None = Field(
        default=None,
        description="若生成了安全探测 SQL，可写在这里供日志 / UI 展示。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="探测补充事实，例如 target_source、read_only、statement_kind。",
    )


class SqlRepairResult(BaseModel):
    """
    `SqlRepairResult`（SQL 修复结果）。

    repair 的职责是提出“更可执行或更合规的 SQL 草案”，
    不是绕过 Guard 直接放行。
    """

    repaired_sql: str | None = Field(
        default=None,
        description="修复后的 SQL。若为 None，表示当前无法给出可靠修复建议。",
    )
    changed: bool = Field(
        default=False,
        description="修复结果是否真的改变了 SQL 文本。",
    )
    reasoning: str | None = Field(
        default=None,
        description="修复说明，主要用于审计与调试。",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="修复阶段仍未解决的问题。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="修复阶段附加事实。",
    )
