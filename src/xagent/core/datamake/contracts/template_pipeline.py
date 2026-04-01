"""
`Template Pipeline Contracts`（模板沉淀链路契约）模块。

这里定义的是 datamake 在“流程草稿 -> compiled DAG -> 模板草稿 -> 模板版本”
链路上共享的中间工件。

设计边界：
- 这些对象是证据与快照，不承接“下一步该做什么”的流程控制职责。
- ReAct 主脑只读取它们的摘要事实来做决策，不能因为某个字段取值自动推进业务动作。
- Runtime 未来可以直接消费 `CompiledDagContract` 或 `TemplateVersionSnapshot`，
  但这仍然是执行输入，不是新的主流程控制器。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CompiledDagStepKind = Literal[
    "sql",
    "http",
    "legacy_scenario",
    "template_version",
    "dubbo",
    "mcp",
]


class CompiledDagStep(BaseModel):
    """
    `CompiledDagStep`（编译后的 DAG 步骤）。

    这是单个步骤在 compiled 阶段被冻结后的执行描述：
    - `step_key` 是 DAG 内稳定引用键，后续依赖关系、参数映射都依赖它。
    - `kind` 只声明步骤落到哪类执行器，不负责表达业务下一步。
    - `input_snapshot/config` 必须是可回放的结构化快照，避免 runtime 再回看自由文本。
    """

    step_key: str = Field(description="步骤稳定键，用于依赖关系与结果引用。")
    name: str = Field(description="步骤展示名，用于调试、审批与回放展示。")
    kind: CompiledDagStepKind = Field(description="步骤类型，对应受控执行器类别。")
    dependencies: list[str] = Field(
        default_factory=list,
        description="当前步骤依赖的上游 step_key 列表。",
    )
    input_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="编译阶段冻结的输入快照，供 runtime 稳定回放。",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="步骤执行配置，如资源标识、超时、映射规则等。",
    )
    approval_policy: str = Field(
        default="none",
        description="步骤级审批策略，仅是执行约束，不直接触发主流程跳转。",
    )


class CompiledDagContract(BaseModel):
    """
    `CompiledDagContract`（编译后的 DAG 契约）。

    这是 FlowDraft 在 compile 阶段冻结出来的可执行中间产物。
    它允许携带 unresolved mappings，明确告诉上层“当前可以编译成功，但还不能安全执行”，
    从而避免把“缺参数”误判成“模板已经可以直接落地”。
    """

    draft_id: str = Field(description="来源草稿标识，用于账本与模板草稿关联。")
    version: int = Field(description="来源草稿版本，保证 compiled 结果和草稿快照一一对应。")
    goal_summary: str = Field(description="当前 DAG 服务的目标摘要，便于审批与回放。")
    steps: list[CompiledDagStep] = Field(
        default_factory=list,
        description="拓扑执行步骤列表。",
    )
    unresolved_mappings: list[dict[str, Any]] = Field(
        default_factory=list,
        description="尚未解析完成的参数映射清单。非空时意味着不能静默直跑。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="补充元信息，如来源系统、风险摘要、编译说明等。",
    )


class TemplateDraftDigest(BaseModel):
    """
    `TemplateDraftDigest`（模板草稿摘要）。

    这是给 Agent / API / 审批界面看的轻量视图，不承载完整模板定义。
    """

    template_draft_id: int | None = Field(default=None, description="模板草稿主键。")
    task_id: str = Field(description="来源任务标识。")
    status: str = Field(default="draft", description="模板草稿状态，仅表达工件生命周期。")
    flow_draft_version: int = Field(description="关联的 FlowDraft 版本。")
    compiled_dag_version: int = Field(description="关联 compiled DAG 的版本。")
    goal_summary: str = Field(default="", description="模板草稿目标摘要。")
    step_count: int = Field(default=0, description="compiled DAG 步骤数。")
    unresolved_mapping_count: int = Field(
        default=0,
        description="尚未解析映射数，用于提醒当前草稿是否可安全发布/执行。",
    )


class TemplateVersionDigest(BaseModel):
    """
    `TemplateVersionDigest`（模板版本摘要）。

    这是给 Agent / API / 审批界面看的已发布模板轻量视图。
    它只表达“已经冻结出的哪个版本可以被复跑”，
    不承接“下一步必须立即执行这个模板”的控制语义。
    """

    template_version_id: int | None = Field(default=None, description="模板版本表主键。")
    template_id: str = Field(description="模板稳定标识。")
    version: int = Field(description="模板版本号。")
    task_id: str | None = Field(default=None, description="来源任务标识。")
    template_name: str = Field(default="", description="模板展示名。")
    goal_summary: str = Field(default="", description="模板业务目标摘要。")
    template_draft_id: int | None = Field(default=None, description="来源模板草稿主键。")
    step_count: int = Field(default=0, description="冻结快照里的步骤数。")
    risk_level: str | None = Field(default=None, description="模板发布时冻结的风险等级摘要。")
    execution_success_rate: float | None = Field(
        default=None,
        description="最近执行成功率。无历史时为空。",
    )
    recent_run_count: int = Field(
        default=0,
        description="用于成功率统计的近期运行样本数。",
    )
    last_success_run_at: datetime | None = Field(
        default=None,
        description="最近一次成功执行时间。",
    )
    visibility: str | None = Field(
        default=None,
        description="模板版本可见性摘要，如 private/shared/global。",
    )
    publisher_user_id: str | None = Field(
        default=None,
        description="发布人标识，用于解释模板归属。",
    )
    approval_passed: bool | None = Field(
        default=None,
        description="发布前关联审批是否明确通过。",
    )


class TemplateCandidateDigest(BaseModel):
    """
    `TemplateCandidateDigest`（模板候选摘要）。

    它表达的是“检索层认为当前可能可复用的模板候选”，
    不是“系统已经决定要执行哪个模板”。
    主脑只能把它当证据参考，仍需显式输出下一步动作。
    """

    template_version_id: int | None = Field(default=None, description="候选模板版本主键。")
    template_id: str = Field(description="模板稳定标识。")
    version: int = Field(description="模板版本号。")
    template_name: str = Field(default="", description="模板展示名。")
    task_id: str | None = Field(default=None, description="来源任务标识。")
    goal_summary: str = Field(default="", description="模板业务目标摘要。")
    step_count: int = Field(default=0, description="候选模板步骤数。")
    score: float = Field(default=0.0, description="当前候选综合匹配分，仅用于排序参考。")
    match_reasons: list[str] = Field(
        default_factory=list,
        description="命中原因摘要，供主脑和 UI 理解为什么这条模板进入候选。",
    )
    matched_params: list[str] = Field(
        default_factory=list,
        description="当前已命中的参数名列表。",
    )
    semantic_similarity: float = Field(
        default=0.0,
        description="embedding/语义相似度信号，数值越高说明任务语义越接近。",
    )
    execution_success_rate: float | None = Field(
        default=None,
        description="最近执行成功率。无历史时为空。",
    )
    recent_run_count: int = Field(
        default=0,
        description="用于成功率估算的近期运行样本数。",
    )
    last_success_run_at: datetime | None = Field(
        default=None,
        description="最近一次成功执行时间。",
    )
    risk_level: str | None = Field(
        default=None,
        description="模板发布时冻结的风险等级。",
    )
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="各排序信号分项得分，供排障和可解释展示使用。",
    )
    visibility: str | None = Field(
        default=None,
        description="候选模板可见性摘要。",
    )
    publisher_user_id: str | None = Field(
        default=None,
        description="候选模板发布人标识。",
    )
    approval_passed: bool | None = Field(
        default=None,
        description="候选模板关联审批是否明确通过。",
    )


class TemplateVersionSnapshot(BaseModel):
    """
    `TemplateVersionSnapshot`（模板版本快照）。

    发布动作必须把当时可执行的模板定义冻结成完整快照，
    这样后续复跑不会受到 FlowDraft 持续演化的影响。
    """

    template_id: str = Field(description="模板稳定标识。")
    version: int = Field(description="模板版本号。")
    compiled_dag: CompiledDagContract = Field(
        description="该模板版本冻结时对应的 compiled DAG。"
    )
    template_version_id: int | None = Field(default=None, description="模板版本表主键。")
    template_name: str = Field(default="", description="模板展示名。")
    task_id: str | None = Field(default=None, description="来源任务标识。")
    goal_summary: str = Field(default="", description="模板版本的业务目标摘要。")
    params_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="模板执行所需参数的结构化约束。",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="发布时冻结的补充元信息，如发布人、审批键、风险说明。",
    )
