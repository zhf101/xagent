"""LLM ReAct 推断引擎。

每一轮会话调用此引擎，由 LLM 产出：
- 当前理解
- 判断依据
- 阻塞点（只有真正阻塞执行的信息缺口才算）
- 推荐动作
- 给用户的问题（动态生成，不是固定问卷）
- 建议 UI 控件
- FlowDraft patch

LLM 无法调用或响应解析失败时降级到 fallback_result()。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .reasoning_packet import ReasoningPacket

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
你是一个智能造数平台的会话推断助手。
你的职责是每轮分析用户意图，输出结构化的推断结果。

你必须严格遵守以下原则：
1. 只有当某个信息真正阻止了后续执行时，才把它列入 blockers
2. 如果已经能推断出意图，不要要求补充非阻塞信息
3. 不要重复问用户已经在历史消息中回答过的问题
4. 第二轮以后，如果信息足够推断目标系统和执行路径，应推进到 COMPILE_PLAN 或 PROBE_STEP，而不是继续澄清
5. ui_hint.interactions 只在 recommended_action 为 ASK_BLOCKING_INFO、ASK_PREFERENCE 或 SHOW_CANDIDATES 时才填写
6. 如果 blockers 为空，recommended_action 不应是 ASK_BLOCKING_INFO，除非你明确要用户补某个真正阻塞的信息

你只输出 JSON，不输出任何其他内容。JSON 结构如下：
{
  "understanding": "...",
  "evidence": ["...", "..."],
  "blockers": ["..."],
  "recommended_action": "EXPLAIN_BASIS | SHOW_CANDIDATES | ASK_BLOCKING_INFO | ASK_PREFERENCE | PROBE_STEP | COMPILE_PLAN | AWAIT_APPROVAL | EXECUTE",
  "allowed_actions": ["...", "..."],
  "question": "...",
  "ui_hint": {
    "type": "clarification_form",
    "interactions": [
      {"type": "text_input", "field": "field_name", "label": "标签", "placeholder": "提示"}
    ]
  },
  "approval_summary": {},
  "draft_patch": {}
}

recommended_action 可选值：
- EXPLAIN_BASIS: 先解释当前判断依据，不推进下一阶段
- SHOW_CANDIDATES: 已有召回候选，需要用户确认选择
- ASK_BLOCKING_INFO: 有阻塞信息缺口，需要用户补充
- ASK_PREFERENCE: 信息基本够了，但需要用户做偏好选择
- PROBE_STEP: 应该对某个候选或步骤做局部试跑
- COMPILE_PLAN: 信息足够，应该编译执行草稿
- AWAIT_APPROVAL: 当前需先等待审批
- EXECUTE: FlowDraft 已就绪，可以正式执行

ui_hint.interactions 中 type 可选：
- text_input: 单行文本
- number_input: 数字
- select_one: 单选，需要 options: [{value, label}]
- multiline_text: 多行文本
"""


def _build_user_prompt(
    *,
    goal: str,
    history_summary: str,
    fact_snapshot: dict[str, Any],
    recall_summary: str,
    current_message: str,
    probe_findings: list[dict[str, Any]],
    draft_status: str | None,
    approval_summary: dict[str, Any],
) -> str:
    parts = []
    parts.append(f"## 用户的原始造数目标\n{goal}")

    if fact_snapshot:
        known = "\n".join(
            f"- {k}: {v}"
            for k, v in fact_snapshot.items()
            if v not in (None, "", [], {})
            and not k.startswith("probe_")
        )
        if known:
            parts.append(f"## 当前已知信息\n{known}")

    if recall_summary:
        parts.append(f"## 入口召回情况\n{recall_summary}")

    if history_summary:
        parts.append(f"## 历史会话摘要\n{history_summary}")

    if current_message and current_message.strip():
        parts.append(f"## 用户本轮输入\n{current_message.strip()}")
    else:
        parts.append("## 用户本轮输入\n（无新输入，请根据当前已有信息判断下一步）")

    if probe_findings:
        findings_text = json.dumps(probe_findings, ensure_ascii=False, indent=2)
        parts.append(f"## 最近 Probe 发现\n{findings_text}")

    if draft_status:
        parts.append(f"## 当前 FlowDraft 状态\n{draft_status}")

    if approval_summary:
        parts.append(
            "## 当前审批与治理摘要\n"
            + json.dumps(approval_summary, ensure_ascii=False, indent=2)
        )

    parts.append(
        "## 你的任务\n"
        "请分析上面的信息，输出结构化推断结果（JSON）。\n"
        "重点判断：当前是否有真正的阻塞信息缺口？还是可以推进到下一阶段？"
    )

    return "\n\n".join(parts)


def _parse_llm_response(raw: str) -> ReasoningPacket:
    """从 LLM 响应中提取 JSON，容错处理。"""
    text = raw.strip()
    # 去掉 markdown 代码块
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    # 找到第一个 { 到最后一个 } 的范围
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("ReAct LLM response has no JSON object: %s", raw[:200])
        return ReasoningPacket(
            understanding="（LLM 响应解析失败）",
            parse_ok=False,
            raw_response=raw,
        )

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        try:
            from json_repair import loads as repair_loads
            data = repair_loads(text[start : end + 1])
        except Exception:
            logger.warning("ReAct LLM JSON repair also failed: %s", raw[:200])
            return ReasoningPacket(
                understanding="（LLM 响应解析失败）",
                parse_ok=False,
                raw_response=raw,
            )

    ui_hint = data.get("ui_hint")
    if not isinstance(ui_hint, dict):
        interactions = list(data.get("suggested_interactions") or [])
        ui_hint = (
            {"type": "clarification_form", "interactions": interactions}
            if interactions
            else {}
        )

    return ReasoningPacket(
        understanding=str(data.get("understanding") or ""),
        evidence=list(data.get("evidence") or []),
        blockers=list(data.get("blockers") or []),
        recommended_action=str(data.get("recommended_action") or "ASK_BLOCKING_INFO"),
        allowed_actions=list(data.get("allowed_actions") or []),
        question=data.get("question") or None,
        ui_hint=dict(ui_hint or {}),
        approval_summary=dict(data.get("approval_summary") or {}),
        draft_patch=dict(data.get("draft_patch") or {}),
        parse_ok=True,
        raw_response=raw,
    )


def fallback_result(*, missing_fields: list[str]) -> ReasoningPacket:
    """LLM 不可用时的保守降级结果。"""
    if not missing_fields:
        return ReasoningPacket(
            understanding="信息已足够，准备构建执行计划。",
            evidence=["关键字段已全部填写"],
            blockers=[],
            recommended_action="COMPILE_PLAN",
            allowed_actions=["COMPILE_PLAN", "EXECUTE"],
            parse_ok=True,
        )
    interactions = [
        {"type": "text_input", "field": f, "label": f, "placeholder": f"请提供 {f}"}
        for f in missing_fields[:3]
    ]
    return ReasoningPacket(
        understanding="（LLM 不可用，降级到字段检查模式）",
        evidence=[],
        blockers=missing_fields,
        recommended_action="ASK_BLOCKING_INFO",
        allowed_actions=["EXPLAIN_BASIS", "ASK_BLOCKING_INFO"],
        question=f"请补充以下信息：{', '.join(missing_fields[:3])}",
        ui_hint={"type": "clarification_form", "interactions": interactions},
        parse_ok=False,
    )


class ConversationReasoningEngine:
    """每轮会话的 LLM ReAct 推断引擎。"""

    def __init__(self, llm: Any):
        """llm: BaseLLM 实例（任何实现了 .chat(messages, temperature) 的对象）。"""
        self._llm = llm

    def reason(
        self,
        *,
        goal: str,
        history_summary: str = "",
        fact_snapshot: dict[str, Any] | None = None,
        recall_summary: str = "",
        current_message: str = "",
        probe_findings: list[dict[str, Any]] | None = None,
        draft_status: str | None = None,
        approval_summary: dict[str, Any] | None = None,
        missing_fields: list[str] | None = None,
    ) -> ReasoningPacket:
        """同步调用 LLM 进行 ReAct 推断，失败时降级。"""
        from xagent.datamakepool.sql_brain.llm_utils import run_async_sync

        user_prompt = _build_user_prompt(
            goal=goal,
            history_summary=history_summary,
            fact_snapshot=dict(fact_snapshot or {}),
            recall_summary=recall_summary,
            current_message=current_message,
            probe_findings=list(probe_findings or []),
            draft_status=draft_status,
            approval_summary=dict(approval_summary or {}),
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = run_async_sync(
                self._llm.chat(messages=messages, temperature=0.2)
            )
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("empty LLM response")
            return _parse_llm_response(raw)
        except Exception as exc:
            logger.warning("ReAct reasoning engine failed: %s", exc)
            return fallback_result(missing_fields=list(missing_fields or []))
