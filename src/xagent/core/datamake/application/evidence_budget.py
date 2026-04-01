"""
`Evidence Budget Manager`（证据预算管理器）模块。

这个模块承接 datamake 主循环里“在进入 LLM 之前如何控制上下文预算”的职责。

当前第一阶段只迁移已有 compact 能力，明确边界如下：
- 负责估算消息体量
- 负责在超预算时触发 compact / 截断兜底
- 负责记录 compact 统计信息

明确不负责：
- 不决定哪些业务动作应该发生
- 不改写证据事实含义
- 不直接构建 round context

后续如果要继续演进到文档里说的 `Always-on Evidence / Search-on-demand Evidence`，
也应该在这个类里扩展，而不是重新把预算逻辑塞回 Pattern。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ...agent.utils.compact import CompactConfig, CompactUtils
from ...agent.utils.llm_utils import clean_messages
from ...model.chat.basic.base import BaseLLM

logger = logging.getLogger(__name__)


class EvidenceBudgetManager:
    """
    `EvidenceBudgetManager`（证据预算管理器）。

    所属层级：
    - 代码分层：`application`
    - 在业务主循环中的位置：位于 Prompt 已经构建完成之后、LLM 调用之前

    当前职责：
    - 对 Prompt 消息做 token 级预算判断
    - 超预算时优先尝试 compact，失败再退化为截断兜底
    - 产出 compact 统计，供外层观测和后续调优使用

    当前约束：
    - 这里只迁移现有 compact 行为，不额外发明新的证据裁剪语义
    - 因而它现在仍是“预算壳”，不是完整的证据编排器
    """

    def __init__(
        self,
        *,
        compact_config: CompactConfig,
        compact_llm: BaseLLM | None,
        extract_content: Callable[[Any], str],
    ) -> None:
        self.compact_config = compact_config
        self.compact_llm = compact_llm
        self.extract_content = extract_content
        self._compact_stats = {"total_compacts": 0, "tokens_saved": 0}
        self.recall_limit = 3
        self.template_candidate_limit = 3
        self.external_evidence_limit = 3
        self.skill_summary_limit = 6
        self.available_resource_limit = 12
        self.match_reason_limit = 3
        self.keyword_limit = 5
        self.tag_limit = 5
        self.text_char_limit = 280
        self.sql_hint_item_limit = 2
        self.sql_hint_char_limit = 160

    def estimate_message_tokens(self, messages: list[dict[str, str]]) -> int:
        """
        估算当前消息体量。

        这里仍复用 xagent 通用 `CompactUtils`，避免 datamake 自己再维护一套
        独立 token 估算逻辑，造成预算标准漂移。
        """

        return CompactUtils.estimate_tokens(messages)

    def prepare_round_context_for_prompt(
        self,
        round_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        产出“允许进入 Prompt 的证据视图”。

        这是当前 datamake 首版显式证据分层规则：
        - `compiled_dag_digest / template_*_digest / ledger_snapshot` 仍然属于 always-on evidence
        - `recall_results / template_version_candidates / external_content_evidence`
          属于 budgeted evidence，会先裁剪再进入 Prompt
        - `available_resources` 仍然保留核心执行约束，但会去掉过长材料

        注意：
        - 这里只做 Prompt 视图层裁剪，不修改原始 round_context
        - 被裁掉的数量会通过 `evidence_budget` 暴露给主脑
        """

        prompt_context = dict(round_context)
        recall_results = round_context.get("recall_results") or []
        template_candidates = round_context.get("template_version_candidates") or []
        external_evidence = round_context.get("external_content_evidence") or []
        skill_catalog_summaries = round_context.get("skill_catalog_summaries") or []
        available_resources = round_context.get("available_resources") or []

        prompt_context["recall_results"] = self._budget_recall_results(recall_results)
        prompt_context["template_version_candidates"] = self._budget_template_candidates(
            template_candidates
        )
        prompt_context["external_content_evidence"] = self._budget_external_evidence(
            external_evidence
        )
        prompt_context["skill_catalog_summaries"] = self._budget_skill_summaries(
            skill_catalog_summaries
        )
        prompt_context["available_resources"] = self._budget_available_resources(
            available_resources
        )
        prompt_context["evidence_budget"] = {
            "recall_results": self._build_budget_summary(
                recall_results,
                prompt_context["recall_results"],
            ),
            "template_version_candidates": self._build_budget_summary(
                template_candidates,
                prompt_context["template_version_candidates"],
            ),
            "external_content_evidence": self._build_budget_summary(
                external_evidence,
                prompt_context["external_content_evidence"],
            ),
            "skill_catalog_summaries": self._build_budget_summary(
                skill_catalog_summaries,
                prompt_context["skill_catalog_summaries"],
            ),
            "available_resources": self._build_budget_summary(
                available_resources,
                prompt_context["available_resources"],
            ),
        }
        prompt_context["evidence_layers"] = self._merge_budget_into_evidence_layers(
            round_context.get("evidence_layers"),
            prompt_context["evidence_budget"],
        )
        return prompt_context

    async def check_and_compact_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        在调用 LLM 前检查上下文长度，必要时执行压缩。

        这是当前 Pattern 进入 LLM 前唯一允许做的预算收缩动作：
        - 不改证据语义
        - 不删关键系统规则
        - 只在预算超限时尝试压缩
        """

        if not self.compact_config.enabled:
            return messages

        estimated_tokens = self.estimate_message_tokens(messages)
        if estimated_tokens <= self.compact_config.threshold:
            return messages

        return await self.compact_datamake_context(messages)

    async def compact_datamake_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        对 datamake 当前轮消息做压缩。

        当前策略保持和迁移前一致：
        - 有 compact_llm 时，优先让模型总结旧上下文
        - 没有 compact_llm 时，退化为保留 system + 最近 user 消息
        """

        original_tokens = self.estimate_message_tokens(messages)
        if self.compact_llm is None:
            return self.fallback_truncate_messages(messages, original_tokens)

        compact_prompt = [
            {
                "role": "system",
                "content": (
                    "你在压缩智能造数 ReAct 上下文。"
                    "请保留：当前任务、最近 observation、待处理审批/交互、资源动作限制、文件上下文。"
                    "请删除：过时细节、冗余字段、重复描述。"
                    "返回仍然是两段消息格式：SYSTEM: ...\\nUSER: ..."
                ),
            },
            {
                "role": "user",
                "content": CompactUtils.format_messages_for_compact(messages),
            },
        ]

        try:
            response = await self.compact_llm.chat(messages=clean_messages(compact_prompt))
            content = self.extract_content(response)
            compacted_messages = self.parse_compact_response(content)
            if not compacted_messages:
                return self.fallback_truncate_messages(messages, original_tokens)

            final_tokens = self.estimate_message_tokens(compacted_messages)
            self._record_compact_stats(
                original_tokens=original_tokens,
                final_tokens=final_tokens,
            )
            return compacted_messages
        except Exception as exc:
            logger.warning("EvidenceBudgetManager 上下文压缩失败，改用截断兜底: %s", exc)
            return self.fallback_truncate_messages(messages, original_tokens)

    def fallback_truncate_messages(
        self,
        messages: list[dict[str, str]],
        original_tokens: int,
    ) -> list[dict[str, str]]:
        """
        压缩失败时的兜底截断逻辑。

        当前依旧保持非常保守的降级策略：
        - 优先保留 `system`
        - 再保留最近一条 `user`
        这样即使 compact 模型不可用，也能最大程度保住控制规则和当前问题。
        """

        system_msg = next((msg for msg in messages if msg.get("role") == "system"), None)
        recent_user_msg = next(
            (msg for msg in reversed(messages) if msg.get("role") == "user"),
            None,
        )
        compacted_messages = [
            msg for msg in [system_msg, recent_user_msg] if msg is not None
        ]
        final_tokens = self.estimate_message_tokens(compacted_messages)
        self._record_compact_stats(
            original_tokens=original_tokens,
            final_tokens=final_tokens,
        )
        return compacted_messages

    def parse_compact_response(self, response: str) -> list[dict[str, str]]:
        """
        解析压缩模型返回的 `SYSTEM: ... / USER: ...` 文本。

        这里仍然容忍 `ASSISTANT:` 前缀，是为了与项目里的通用 compact 约定保持一致，
        避免未来替换 compact 模型时因格式轻微漂移直接失效。
        """

        messages: list[dict[str, str]] = []
        current_role: str | None = None
        current_content: list[str] = []

        for raw_line in response.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("SYSTEM:", "USER:", "ASSISTANT:")):
                if current_role and current_content:
                    messages.append(
                        {
                            "role": current_role.lower(),
                            "content": "\n".join(current_content),
                        }
                    )
                parts = line.split(":", 1)
                current_role = parts[0]
                current_content = [parts[1].strip()] if len(parts) > 1 else []
            elif current_role:
                current_content.append(line)

        if current_role and current_content:
            messages.append(
                {
                    "role": current_role.lower(),
                    "content": "\n".join(current_content),
                }
            )

        return messages

    def get_stats(self) -> dict[str, Any]:
        """
        返回当前 compact 统计信息。

        这里同时暴露 `enabled/threshold`，是为了让外层调用方在看统计时
        能同时知道“为什么没有发生 compact”，而不是只能看到一堆零值。
        """

        return {
            **self._compact_stats,
            "enabled": self.compact_config.enabled,
            "threshold": self.compact_config.threshold,
        }

    def _record_compact_stats(
        self,
        *,
        original_tokens: int,
        final_tokens: int,
    ) -> None:
        """
        更新 compact 统计。

        统计逻辑集中收口到这里，避免 fallback / compact 成功两条路径
        分散维护计数器，后续扩展多种预算策略时更容易统一。
        """

        self._compact_stats["total_compacts"] += 1
        self._compact_stats["tokens_saved"] += max(original_tokens - final_tokens, 0)

    def _budget_recall_results(
        self,
        recall_results: list[Any],
    ) -> list[dict[str, Any]]:
        """
        将 recall 结果压成更稳定的 Prompt 摘要。

        recall 的原始 `content/metadata` 往往最长，也最容易把 Prompt 撑爆。
        这里保留“为什么命中 + 命中了什么”所需的核心信息，去掉长正文细节。
        """

        items: list[dict[str, Any]] = []
        for item in recall_results[: self.recall_limit]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "memory_id": item.get("memory_id"),
                    "category": item.get("category"),
                    "keywords": self._limit_str_list(
                        item.get("keywords"),
                        self.keyword_limit,
                    ),
                    "tags": self._limit_str_list(item.get("tags"), self.tag_limit),
                    "summary": self._truncate_text(
                        item.get("summary") or item.get("content"),
                        self.text_char_limit,
                    ),
                    "timestamp": item.get("timestamp"),
                    "metadata_digest": self._digest_mapping(item.get("metadata")),
                }
            )
        return items

    def _budget_template_candidates(
        self,
        candidates: list[Any],
    ) -> list[dict[str, Any]]:
        """
        对模板候选做 Prompt 级 digest。

        模板候选对当前轮很重要，所以保留：
        - 身份字段
        - score
        - 前几条 match reason
        其余长说明不直接进入 Prompt。
        """

        items: list[dict[str, Any]] = []
        for item in candidates[: self.template_candidate_limit]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "template_version_id": item.get("template_version_id"),
                    "template_id": item.get("template_id"),
                    "version": item.get("version"),
                    "task_id": item.get("task_id"),
                    "score": item.get("score"),
                    "match_reasons": self._limit_str_list(
                        item.get("match_reasons"),
                        self.match_reason_limit,
                    ),
                }
            )
        return items

    def _budget_external_evidence(
        self,
        evidences: list[Any],
    ) -> list[dict[str, Any]]:
        """
        对外部证据做 budget。

        这类内容本来就属于不可信候选证据，因此只保留来源、标签和摘要。
        """

        items: list[dict[str, Any]] = []
        for item in evidences[: self.external_evidence_limit]:
            if not isinstance(item, dict):
                continue
            source = item.get("source") or item.get("content_source")
            label = item.get("label") or item.get("content_trust")
            items.append(
                {
                    "source": source,
                    "label": label,
                    "summary": self._truncate_text(
                        item.get("summary") or item.get("content"),
                        self.text_char_limit,
                    ),
                    "trust_notice": self._truncate_text(
                        item.get("trust_notice"),
                        self.text_char_limit,
                    ),
                }
            )
        return items

    def _budget_skill_summaries(
        self,
        skills: list[Any],
    ) -> list[dict[str, Any]]:
        """
        对能力目录摘要做 budget。
        """

        items: list[dict[str, Any]] = []
        for item in skills[: self.skill_summary_limit]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": item.get("name"),
                    "summary": self._truncate_text(
                        item.get("summary"),
                        self.text_char_limit,
                    ),
                    "available": item.get("available"),
                    "safety_level": item.get("safety_level"),
                }
            )
        return items

    def _budget_available_resources(
        self,
        resources: list[Any],
    ) -> list[dict[str, Any]]:
        """
        对资源目录做 Prompt 级摘要。

        资源目录仍然是执行动作选择的核心护栏，因此保留动作身份、风险和审批要求。
        但对 `sql_context_hints` 这类长材料只保留计数和短摘要，避免主脑每轮都背整份 SQL 文档。
        """

        items: list[dict[str, Any]] = []
        for item in resources[: self.available_resource_limit]:
            if not isinstance(item, dict):
                continue
            normalized = {
                "resource_key": item.get("resource_key"),
                "operation_key": item.get("operation_key"),
                "adapter_kind": item.get("adapter_kind"),
                "description": self._truncate_text(
                    item.get("description"),
                    self.text_char_limit,
                ),
                "risk_level": item.get("risk_level"),
                "supports_probe": item.get("supports_probe"),
                "requires_approval": item.get("requires_approval"),
                "resource_policy": self._digest_mapping(item.get("resource_policy")),
            }
            sql_hints = item.get("sql_context_hints")
            if isinstance(sql_hints, dict):
                sql_context = sql_hints.get("sql_context")
                sources = sql_hints.get("sources")
                normalized["sql_context_hints"] = {
                    "schema_ddl_preview": self._limit_and_truncate_str_list(
                        sql_context.get("schema_ddl") if isinstance(sql_context, dict) else [],
                        self.sql_hint_item_limit,
                        self.sql_hint_char_limit,
                    ),
                    "example_sqls_preview": self._limit_and_truncate_str_list(
                        sql_context.get("example_sqls") if isinstance(sql_context, dict) else [],
                        self.sql_hint_item_limit,
                        self.sql_hint_char_limit,
                    ),
                    "documentation_snippets_preview": self._limit_and_truncate_str_list(
                        sql_context.get("documentation_snippets")
                        if isinstance(sql_context, dict)
                        else [],
                        self.sql_hint_item_limit,
                        self.sql_hint_char_limit,
                    ),
                    "source_summaries": self._budget_sql_hint_sources(sources),
                }
            items.append(normalized)
        return items

    def _budget_sql_hint_sources(self, sources: Any) -> list[dict[str, Any]]:
        """
        裁剪 SQL hint 来源摘要。
        """

        if not isinstance(sources, list):
            return []
        items: list[dict[str, Any]] = []
        for source in sources[: self.sql_hint_item_limit]:
            if not isinstance(source, dict):
                continue
            items.append(
                {
                    "source_id": source.get("source_id"),
                    "match_reason": source.get("match_reason"),
                    "summary": self._truncate_text(
                        source.get("summary"),
                        self.sql_hint_char_limit,
                    ),
                }
            )
        return items

    def _build_budget_summary(
        self,
        original_items: list[Any],
        prompt_items: list[Any],
    ) -> dict[str, int]:
        """
        记录某类证据的裁剪情况。
        """

        total = len(original_items)
        in_prompt = len(prompt_items)
        return {
            "total": total,
            "in_prompt": in_prompt,
            "omitted": max(total - in_prompt, 0),
        }

    def _merge_budget_into_evidence_layers(
        self,
        evidence_layers: Any,
        evidence_budget: dict[str, dict[str, int]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        把预算裁剪结果合并回显式证据分层说明。

        这样主脑看到的不只是“有哪些层”，还知道某些 search-on-demand 层
        当前只展示了多少条摘要。
        """

        if not isinstance(evidence_layers, dict):
            return {}

        merged: dict[str, list[dict[str, Any]]] = {}
        for layer_name in ("always_on", "search_on_demand"):
            raw_items = evidence_layers.get(layer_name)
            if not isinstance(raw_items, list):
                merged[layer_name] = []
                continue
            layer_items: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                field_name = normalized.get("field")
                if isinstance(field_name, str) and field_name in evidence_budget:
                    normalized["budget"] = dict(evidence_budget[field_name])
                layer_items.append(normalized)
            merged[layer_name] = layer_items
        return merged

    def _digest_mapping(self, value: Any) -> dict[str, Any] | None:
        """
        对任意 mapping 做浅层 digest。

        这里不做深层递归，是为了避免 metadata 一多又把 Prompt 带回膨胀状态。
        """

        if not isinstance(value, dict):
            return None
        digested: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)) or item is None:
                digested[str(key)] = (
                    self._truncate_text(item, self.text_char_limit)
                    if isinstance(item, str)
                    else item
                )
            elif isinstance(item, list):
                digested[str(key)] = self._limit_str_list(item, self.keyword_limit)
        return digested

    def _limit_str_list(self, values: Any, limit: int) -> list[str]:
        """
        限制字符串列表长度，并清理空值。
        """

        if not isinstance(values, list):
            return []
        items: list[str] = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            items.append(text)
            if len(items) >= limit:
                break
        return items

    def _limit_and_truncate_str_list(
        self,
        values: Any,
        limit: int,
        char_limit: int,
    ) -> list[str]:
        """
        限制字符串列表长度，并截断单条内容。
        """

        return [
            self._truncate_text(value, char_limit)
            for value in self._limit_str_list(values, limit)
        ]

    def _truncate_text(self, value: Any, char_limit: int) -> str | None:
        """
        截断过长文本，避免长正文直接进入 Prompt。
        """

        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) <= char_limit:
            return text
        return f"{text[:char_limit]}..."
