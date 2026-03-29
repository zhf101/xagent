"""ReAct 推断层的输入/输出模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningResult:
    """LLM 每轮 ReAct 推断的结构化输出。

    LLM 负责产出这个结构，decision_engine 根据这个结构决定下一步动作。
    前端展示的 message 和 interactions 完全由 LLM 动态生成，
    不再由后端硬编码字段控件。
    """

    # LLM 当前对用户意图的理解摘要
    understanding: str

    # LLM 推断出的判断依据（召回情况、已知字段等）
    evidence: list[str] = field(default_factory=list)

    # 当前阻塞点列表（真正阻止进入下一阶段的信息缺口）
    blockers: list[str] = field(default_factory=list)

    # 推荐动作（与 decision_engine 的 recommended_action 对齐）
    recommended_action: str = "REQUEST_CLARIFICATION"

    # 若需要问用户，这是 LLM 动态生成的问题文本（只问阻塞项，不是固定问卷）
    question: str | None = None

    # LLM 建议的 UI 交互控件（可为空，表示纯文本对话即可）
    # 格式：[{type, field, label, options?, placeholder?}]
    suggested_interactions: list[dict[str, Any]] = field(default_factory=list)

    # LLM 对 FlowDraft 的 patch 建议（可为空）
    # 格式：{steps?: [...], param_graph?: {...}}
    draft_patch: dict[str, Any] = field(default_factory=dict)

    # 解析是否成功（False 表示 LLM 响应解析失败，需降级）
    parse_ok: bool = True

    # 原始 LLM 响应文本（调试用）
    raw_response: str = ""
