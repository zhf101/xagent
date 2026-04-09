"""
Result analysis logic for DAG plan-execute pattern.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from json_repair import loads as repair_loads

from ....model.chat.basic.base import BaseLLM
from ....model.chat.token_context import add_token_usage
from ...exceptions import LLMResponseError
from ...trace import (
    Tracer,
    trace_memory_generate_end,
    trace_memory_generate_start,
    trace_task_llm_call_end,
    trace_task_llm_call_start,
)
from ...utils.llm_utils import clean_messages, extract_json_from_markdown
from .schemas import GoalCheckResponse

logger = logging.getLogger(__name__)


class ResultAnalyzer:
    """Handles result analysis and goal achievement checking"""

    def __init__(self, llm: BaseLLM, tracer: Tracer):
        self.llm = llm
        self.tracer = tracer

    async def check_goal_achievement(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        file_outputs: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Check if the goal has been achieved and generate memory storage insights and final answer

        Returns a dictionary with:
        - achieved: bool - whether the goal was achieved
        - reason: str - explanation of goal achievement status
        - confidence: float - confidence level (0.0-1.0)
        - final_answer: str - comprehensive final answer if achieved, otherwise analysis of what's missing
        - memory_insights: dict - memory storage insights
        """
        logger.info(
            "Checking if goal has been achieved, generating final answer, and memory insights"
        )

        prompt = self._build_comprehensive_goal_check_prompt(
            goal, history, file_outputs
        )

        try:
            # Trace LLM call for goal check
            goal_check_task_id = f"goal_check_{int(time.time())}"
            await trace_task_llm_call_start(
                self.tracer,
                goal_check_task_id,
                data={
                    "goal": goal,
                    "history_length": len(history),
                    "task_type": "comprehensive_goal_check",
                },
            )

            # Trace LLM call for final answer (separate event for frontend compatibility)
            final_answer_task_id = f"final_answer_{int(time.time())}"
            await trace_task_llm_call_start(
                self.tracer,
                final_answer_task_id,
                data={
                    "goal": goal[:200],
                    "history_length": len(history),
                    "task_type": "final_answer_generation",
                },
            )

            # Trace memory generation start
            await trace_memory_generate_start(
                self.tracer,
                goal_check_task_id,
                data={
                    "goal": goal,
                    "history_length": len(history),
                    "analysis_type": "goal_check_with_memory_insights",
                },
            )

            # Clean messages before sending to LLM
            cleaned_prompt = clean_messages(prompt)

            # Prepare output_config with JSON schema from Pydantic model
            # This ensures the required fields are present and provides type safety
            # Note: ClaudeLLM will automatically fix the schema for API compatibility
            output_config = {
                "format": {
                    "type": "json_schema",
                    "schema": GoalCheckResponse.model_json_schema(),
                }
            }

            # Call LLM for comprehensive goal checking and insight generation
            # Using _call_llm_with_retry for automatic fallback from JSON mode to normal mode
            response = await self._call_llm_with_retry(
                messages=cleaned_prompt,
                output_config=output_config,
            )

            # Debug: log response type and structure
            logger.debug(f"LLM response type: {type(response)}, value: {response!r}")

            # Extract content from response
            if isinstance(response, dict):
                content = response.get("content", response)
            elif isinstance(response, tuple):
                # If response is a tuple, extract first element (content)
                logger.warning(f"Unexpected tuple response from LLM: {response}")
                content = response[0] if len(response) > 0 else str(response)
            else:
                # Direct string or other type
                content = response

            logger.info(
                f"Comprehensive goal check response received (first 500 chars): {str(content)[:500]}"
            )
            logger.debug(
                f"Full response: {content!r}"
            )  # Log full response for debugging

            # Extract JSON from markdown if response_format was specified
            content_before_extraction = content
            content = extract_json_from_markdown(content)

            # Debug: Log if extraction occurred
            if content != content_before_extraction:
                logger.info(
                    "⚠️ JSON extraction changed content (markdown code block found)"
                )
                logger.info(
                    f"   Before (first 150 chars): {str(content_before_extraction)[:150]}"
                )
                logger.info(f"   After (first 150 chars):  {str(content)[:150]}")
            else:
                logger.debug(
                    "✅ No markdown extraction needed (content is already JSON)"
                )

            # Parse response
            try:
                result = None

                # Check if content is a JSON array (starts with '[')
                content_stripped = content.strip()
                if content_stripped.startswith("["):
                    # LLM returned a JSON array instead of object
                    # This might happen if the model wrapped the response in an array
                    logger.warning(
                        "LLM returned JSON array instead of object, attempting to extract first element"
                    )
                    try:
                        parsed_array = repair_loads(content, logging=False)
                        if isinstance(parsed_array, list) and len(parsed_array) > 0:
                            # Use first element of array directly as result
                            result = parsed_array[0]
                            logger.info(
                                f"✅ Extracted first element from JSON array: {type(result).__name__}"
                            )
                        else:
                            raise LLMResponseError(
                                "LLM returned empty or invalid JSON array",
                                response=content,
                                expected_format="JSON object with goal achievement and memory insights",
                            )
                    except LLMResponseError:
                        raise
                    except Exception as e:
                        raise LLMResponseError(
                            f"Failed to parse JSON array response: {str(e)}",
                            response=content,
                            expected_format="JSON object with goal achievement and memory insights",
                            cause=e,
                        )
                else:
                    # Normal parsing: content should be a JSON object
                    # Note: logging must be False to avoid tuple return (json, repair_log)
                    result = repair_loads(content, logging=False)

                    # Debug: Log the parsed result type
                    logger.debug(f"repair_loads returned type: {type(result).__name__}")
                    if isinstance(result, list):
                        logger.debug(
                            f"repair_loads returned list with {len(result)} elements"
                        )
                        if len(result) > 0:
                            logger.debug(
                                f"First element type: {type(result[0]).__name__}"
                            )
                            logger.debug(
                                f"First element (first 200 chars): {str(result[0])[:200]}"
                            )

                # Validate result is a dict
                if not isinstance(result, dict):
                    raise LLMResponseError(
                        f"Comprehensive goal check response is not a JSON object. Got: {type(result).__name__}",
                        response=content,
                        expected_format="JSON object with goal achievement and memory insights",
                    )

                # Validate required fields
                if "achieved" not in result:
                    raise LLMResponseError(
                        "Comprehensive goal check response missing 'achieved' field",
                        response=content,
                        expected_format="JSON object with goal achievement and memory insights",
                    )

                if "reason" not in result:
                    result["reason"] = "No reason provided"

                # Ensure memory insights are present
                if "memory_insights" not in result:
                    result["memory_insights"] = {
                        "should_store": False,
                        "reason": "No memory insights provided",
                        "classification": {
                            "primary_domain": "General Task",
                            "secondary_domains": [],
                            "task_type": "General",
                            "complexity_level": "Medium",
                            "keywords": ["general", "task"],
                        },
                        "execution_insights": "",
                        "failure_analysis": "",
                        "success_factors": "",
                        "learned_patterns": "",
                        "improvement_suggestions": "",
                        "user_preferences": "",
                        "behavioral_patterns": "",
                    }

                # Ensure final_answer is present
                if "final_answer" not in result or not result["final_answer"]:
                    # Generate a simple fallback answer if missing
                    if result.get("achieved", False):
                        result["final_answer"] = (
                            f"Task completed successfully. {result.get('reason', 'Goal achieved.')}"
                        )
                    else:
                        result["final_answer"] = (
                            f"TASK FAILED: {result.get('reason', 'Goal not achieved.')}"
                        )

                logger.info(
                    f"Comprehensive goal check result: achieved={result['achieved']}, "
                    f"reason={result['reason']}, "
                    f"should_store_memory={result['memory_insights']['should_store']}, "
                    f"final_answer_length={len(result.get('final_answer', ''))}"
                )

                # Trace goal check LLM call completion
                await trace_task_llm_call_end(
                    self.tracer,
                    goal_check_task_id,
                    data={
                        "goal": goal[:200],
                        "history_length": len(history),
                        "task_type": "comprehensive_goal_check",
                        "response_length": len(content) if content else 0,
                        "goal_achieved": result["achieved"],
                        "goal_reason": result["reason"],
                        "goal_confidence": result.get("confidence", 0.0),
                        "memory_should_store": result["memory_insights"][
                            "should_store"
                        ],
                        "memory_reason": result["memory_insights"]["reason"],
                    },
                )

                # Trace final answer LLM call completion (for frontend compatibility)
                await trace_task_llm_call_end(
                    self.tracer,
                    final_answer_task_id,
                    data={
                        "goal": goal[:200],
                        "history_length": len(history),
                        "task_type": "final_answer_generation",
                        "response_length": len(result.get("final_answer", "")),
                    },
                )

                # Trace memory generation end
                await trace_memory_generate_end(
                    self.tracer,
                    goal_check_task_id,
                    data={
                        "insights_generated": True,
                        "should_store": result["memory_insights"]["should_store"],
                        "reason": result["memory_insights"]["reason"],
                        "source": "goal_check",
                    },
                )

                return result

            except json.JSONDecodeError as e:
                # Check if response looks like a model rejection/safety filter message
                raise LLMResponseError(
                    f"Failed to parse response as JSON. This might be due to model content filtering. Response: {content}",
                    response=content,
                    expected_format="JSON object with goal achievement and memory insights",
                    cause=e,
                )

        except Exception as e:
            if isinstance(e, LLMResponseError):
                raise

            # Wrap other exceptions
            raise LLMResponseError(
                f"Comprehensive goal achievement check failed: {str(e)}",
                context={"goal": goal[:100], "history_length": len(history)},
                cause=e,
            )

    def _build_comprehensive_goal_check_prompt(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        file_outputs: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build prompt for comprehensive goal achievement checking, final answer generation, and memory insight generation"""

        execution_summary = self._summarize_execution_history(history)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build file outputs section
        file_outputs_section = ""
        if file_outputs:
            file_outputs_section = "\n\nOutput Files:\n"
            for i, file_info in enumerate(file_outputs, 1):
                filename = file_info.get("filename", "")
                file_id = file_info.get("file_id", "")
                file_outputs_section += f"  {i}. {filename} (file_id: {file_id})\n"
            file_outputs_section += "\n"

        # Detect goal language
        goal_has_chinese = any("\u4e00" <= c <= "\u9fff" for c in goal)
        goal_has_english = any(c.isascii() and c.isalpha() for c in goal)
        detected_language = (
            "Chinese"
            if goal_has_chinese
            else ("English" if goal_has_english else "the same")
        )

        system_prompt = (
            "你是一个 AI 助手，负责评估任务执行情况并综合整理结果。\n"
            "根据执行历史，你必须：\n"
            "1. 判断声明的目标是否完成\n"
            "2. 生成一个全面的最终答案，回应原始目标\n"
            "3. 分析此任务是否包含值得作为记忆存储的经验\n\n"
            "关键提示：当评估带有用户修改的目标达成情况时：\n"
            "- 如果你看到 [User Modification: '...'] 标记，说明用户更改了原始需求\n"
            "- 根据最新的用户需求来评估目标达成情况\n"
            "- 如果最终结果满足修改后的需求，则目标已达成\n\n"
            "关键语言要求：你必须使用与原始目标相同的语言进行回复！\n"
            "如果目标是英文，仅用英文回复。\n"
            "如果目标是中文，仅用中文回复。\n"
            "绝不要混合使用语言。你的整个回复必须与目标使用相同的语言。\n\n"
            "返回包含目标达成状态、最终答案和记忆洞察的 JSON。"
        )

        goal_analysis_prompt = f"""目标达成分析和最终答案：
原始目标：{goal}
当前时间：{current_time}

执行历史摘要：
{execution_summary}
{file_outputs_section}
重要提示：你的最终答案必须仅使用 {detected_language}，与目标的语言保持一致。

请全面分析此任务执行情况，返回 JSON 格式：

{{
  "achieved": true/false,
  "reason": "清楚解释为什么目标达成/未达成",
  "confidence": 0.0-1.0,
  "final_answer": "全面的最终答案，通过综合所有执行结果来回应原始目标。如果达成：提供完整、结构良好的回复，包含成功确认。如果未达成：解释已完成的内容和剩余的工作。必须使用与目标相同的语言。",
  "memory_insights": {{
    "should_store": true/false,
    "reason": "简要解释为什么应该/不应该存储为记忆",

    "classification": {{
      "primary_domain": "主要领域类别（如：数据分析、软件开发、机器学习）",
      "secondary_domains": ["相关领域类别"],
      "task_type": "具体任务类型",
      "complexity_level": "Simple/Medium/Complex",
      "keywords": ["用于检索的相关关键词"]
    }},

    "execution_insights": "分析成功策略、效率优化和资源利用",
    "failure_analysis": "失败的根本原因分析和已实施的解决方案",
    "success_factors": "影响结果的关键决策和策略有效性",
    "learned_patterns": "可应用于未来类似任务的抽象模式",
    "improvement_suggestions": "具体的可操作优化和改进建议",

    "user_preferences": "从任务需求和执行中分析的用户偏好（如：偏好的输出格式、详细程度、沟通风格、工具使用模式）",
    "behavioral_patterns": "可观察的用户行为模式（如：常见任务类型、时间偏好、失败容忍度、迭代模式）"
  }}
}}

最终答案指南：
- 如果目标成功达成且有意义的结果，清楚表明成功
- 如果目标因失败或缺少信息而无法达成，清楚表明失败
- 为你提供成功/失败判定的清晰推理
- 如果失败，解释出了什么问题以及可以如何改进
- 当有输出文件时，你必须使用上面显示的精确格式包含它们：
  - 对于图片：`![description](file:file_id)`
  - 对于其他文件：`[filename](file:file_id)`
  - 始终使用 `file:` 前缀后跟精确的 file_id
- 将相关文件分组在清晰的标题下
- 重要提示：如果你确定目标未达成，你必须以 'TASK FAILED: ' 开始你的最终答案，后跟清晰的解释（使用与目标相同的语言）

严格的记忆存储标准：

存储决策：仅当此执行包含具有明显未来价值的 exceptional、非显而易见的洞察时，才将 should_store 设置为 true。

要求（必须全部满足）：
1. **独特价值** - 洞察不易通过一般知识或简单推理获得
2. **非常规** - 执行超出标准模式和方法
3. **可复用** - 学习可应用于多种未来场景，而不仅是此特定情况
4. **可操作** - 为改进未来任务执行提供具体指导

自动拒绝（store = false）：
- 遵循标准工作流程的常规任务完成
- 对"有效"过程的通用描述
- 没有独特洞察力的常见问题解决方法
- 不提供新学习内容的明显策略
- 其他地方容易获得的一般信息
- 没有深入分析的简单成功/失败

重点关注：
- **用户偏好**：清晰的行为模式、沟通风格偏好、输出格式要求
- **失败分析**：非显而易见的根本原因和发现的有效解决方案
- **创新**：展示比标准方法有显著改进的新方法
- **效率**：大幅改善资源利用或时间复杂度的发现

存储阈值：极其保守。除非有令人信服的证据表明有 exceptional 价值，否则默认 should_store = false。如有疑问，拒绝存储。"""

        # Try to extract and reuse existing messages context from history
        working_messages = [{"role": "system", "content": system_prompt}]

        # Look for messages in the history (from step execution results)
        context_messages = []
        for iteration in history:
            if "results" in iteration:
                for result in iteration.get("results", []):
                    if "messages" in result.get("result", {}):
                        messages = result["result"]["messages"]
                        if isinstance(messages, list):
                            context_messages.extend(messages)

        # If we found contextual messages, use them as conversation history
        if context_messages:
            # Add relevant contextual messages (excluding system prompts to avoid conflicts)
            for msg in context_messages:
                if msg.get("role") != "system":  # Avoid system prompt conflicts
                    working_messages.append(msg)

        # Add the goal analysis as the final user message
        working_messages.append({"role": "user", "content": goal_analysis_prompt})

        return working_messages

    def _summarize_execution_history(self, history: List[Dict[str, Any]]) -> str:
        """Create a summary of execution history for goal checking"""
        if not history:
            return "No execution history"

        summary_parts = []

        for i, iteration_data in enumerate(history, 1):
            iteration_summary = f"Iteration {i}:"

            # Check if this iteration was triggered by continuation
            if iteration_data.get("continuation"):
                continuation = iteration_data["continuation"]
                user_input = continuation.get("user_input", "")
                iteration_summary += f" [User Modification: '{user_input}']"

            if "plan" in iteration_data:
                plan_data = iteration_data["plan"]
                iteration_summary += (
                    f" Plan with {len(plan_data.get('steps', []))} steps"
                )

            if "results" in iteration_data:
                results = iteration_data["results"]
                completed = len([r for r in results if r.get("status") == "completed"])
                failed = len([r for r in results if r.get("status") == "failed"])
                iteration_summary += (
                    f", Results: {completed} completed, {failed} failed"
                )

                # Add actual content from successful steps for goal checking
                if completed > 0:
                    iteration_summary += "\nSuccessful Step Results:\n"
                    for result in results:
                        if result.get("status") == "completed":
                            step_name = result.get("step_name", "Unknown")
                            step_result = result.get("result", {})
                            content = self._extract_content_from_result(step_result)
                            # Include full content for goal checking
                            iteration_summary += f"- {step_name}: {content}\n"

            summary_parts.append(iteration_summary)

        return "\n".join(summary_parts) if summary_parts else "No execution history"

    async def generate_final_answer(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        file_outputs: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate a comprehensive final answer based on execution results"""
        logger.info("Generating comprehensive final answer")

        prompt = self._build_final_answer_prompt(goal, history, file_outputs)

        try:
            # Trace LLM call
            trace_task_id = f"final_answer_{int(time.time())}"
            await trace_task_llm_call_start(
                self.tracer,
                trace_task_id,
                data={
                    "goal": goal[:200],  # Truncate for trace
                    "history_length": len(history),
                    "task_type": "final_answer_generation",
                },
            )

            # Clean messages before sending to LLM
            cleaned_prompt = clean_messages(prompt)
            # Call LLM to generate final answer
            # Use streaming API to collect complete response
            full_content = ""

            async for chunk in self.llm.stream_chat(messages=cleaned_prompt):
                if chunk.is_token():
                    full_content += chunk.delta
                elif chunk.is_error():
                    raise RuntimeError(f"LLM stream error: {chunk.content}")

            content = full_content

            # Trace LLM call completion
            await trace_task_llm_call_end(
                self.tracer,
                trace_task_id,
                data={
                    "goal": goal[:200],  # Truncate for trace
                    "history_length": len(history),
                    "task_type": "final_answer_generation",
                    "response_length": len(content) if content else 0,
                },
            )

            return content.strip()

        except Exception as e:
            logger.error(f"Error generating final answer: {e}")
            # Fallback to simple summary
            return self._generate_fallback_summary(history)

    def _build_final_answer_prompt(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        file_outputs: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """Build prompt for generating comprehensive final answer"""

        execution_summary = self._summarize_execution_results(history)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build file outputs section for the prompt
        file_outputs_section = ""
        if file_outputs:
            file_outputs_section = "\n\n输出文件：\n"
            for i, file_info in enumerate(file_outputs, 1):
                filename = file_info.get("filename", "")
                file_id = file_info.get("file_id", "")
                file_outputs_section += f"  {i}. {filename} (file_id: {file_id})\n"
            file_outputs_section += "\n"

        system_prompt = (
            "你是一个 AI 助手，负责将执行结果综合成全面的答案。\n"
            "根据执行历史和多个步骤的结果，生成一个完整的、"
            "结构良好的回复，直接回应原始目标。\n"
            "整合所有成功步骤的信息，提供详尽的答案。\n\n"
            "关键语言要求：你必须使用与原始目标相同的语言进行回复！\n"
            "如果目标是英文，仅用英文回复。\n"
            "如果目标是中文，仅用中文回复。\n"
            "如果目标是日文，仅用日文回复。\n"
            "绝不要混合使用语言。你的整个回复必须与目标使用相同的语言。\n\n"
            "重要提示：评估结果时：\n"
            "1. 如果目标成功达成且有意义的结果，表明成功\n"
            "2. 如果目标因失败或缺少信息而无法达成，表明失败\n"
            "3. 为你提供成功/失败判定的清晰推理\n"
            "4. 如果失败，解释出了什么问题以及可以如何改进\n\n"
            "关键提示：如果你确定目标未达成，你必须以 "
            "'TASK FAILED: ' 开始你的回复，后跟清晰的失败解释（使用与目标相同的语言）。\n\n"
            "文件输出格式：\n"
            "当有输出文件时，你必须使用 Markdown 链接格式将它们包含在你的回复中：\n"
            "- 每个文件使用此精确格式：`[filename](file:file_id)`\n"
            "- 示例：`[report.html](file:550e8400-e29b-41d4-a716-446655440000)`\n"
            "- 将相关文件分组在清晰的标题下\n"
            "- 始终在回复末尾以清晰、有序的方式包含文件链接\n"
            "- 这允许用户点击文件链接在右侧面板中预览它们"
        )

        # Detect goal language for explicit instruction
        goal_has_chinese = any("\u4e00" <= c <= "\u9fff" for c in goal)
        goal_has_english = any(c.isascii() and c.isalpha() for c in goal)
        detected_language = (
            "Chinese"
            if goal_has_chinese
            else ("English" if goal_has_english else "the same")
        )

        user_prompt = (
            f"原始目标：{goal}\n\n"
            f"当前时间：{current_time}\n\n"
            f"执行结果：\n{execution_summary}\n"
            f"{file_outputs_section}"
            f"重要提示：你的回复必须仅使用 {detected_language}，与目标的语言保持一致。\n\n"
            f"请生成一个全面的最终答案，通过综合执行期间收集的所有信息来回应原始目标。"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _summarize_execution_results(self, history: List[Dict[str, Any]]) -> str:
        """Create a detailed summary of execution results with actual content"""
        if not history:
            return "No execution history available"

        summary_parts = []

        for i, iteration_data in enumerate(history, 1):
            iteration_summary = f"Iteration {i}:\n"

            # Check if this iteration was triggered by continuation
            if iteration_data.get("continuation"):
                continuation = iteration_data["continuation"]
                user_input = continuation.get("user_input", "")
                iteration_summary += f"[User Modified Goal: '{user_input}']\n"

            if "results" in iteration_data:
                results = iteration_data["results"]
                successful_results = [
                    r for r in results if r.get("status") == "completed"
                ]

                if successful_results:
                    iteration_summary += "Successful Steps:\n"
                    for result in successful_results:
                        step_name = result.get("step_name", "Unknown")
                        step_result = result.get("result", {})
                        content = self._extract_content_from_result(step_result)
                        iteration_summary += f"- {step_name}: {content[:200]}{'...' if len(content) > 200 else ''}\n"

                failed_results = [r for r in results if r.get("status") == "failed"]
                if failed_results:
                    iteration_summary += "Failed Steps:\n"
                    for result in failed_results:
                        step_name = result.get("step_name", "Unknown")
                        error = result.get("error", "Unknown error")
                        iteration_summary += f"- {step_name}: {error}\n"

            summary_parts.append(iteration_summary)

        return "\n".join(summary_parts)

    def _extract_content_from_result(self, result: Dict[str, Any]) -> str:
        """Extract meaningful content from a step result"""
        if not isinstance(result, dict):
            return str(result)

        # Try common content keys in priority order
        content_keys = [
            "output",
            "analysis_result",
            "direct_analysis",
            "content",
            "text",
            "answer",
            "response",
        ]

        for key in content_keys:
            if key in result and result[key]:
                content = result[key]
                if isinstance(content, dict):
                    # If it's a dict, try nested keys
                    for nested_key in ["output", "content", "text"]:
                        if nested_key in content:
                            return str(content[nested_key])
                return str(content)

        # If no specific content found, return string representation
        return str(result)

    def _generate_fallback_summary(self, history: List[Dict[str, Any]]) -> str:
        """Generate a simple fallback summary when LLM generation fails"""
        if not history:
            return "No execution results available"

        last_iteration = history[-1]
        results = last_iteration.get("results", [])
        successful = len([r for r in results if r.get("status") == "completed"])
        failed = len([r for r in results if r.get("status") == "failed"])

        if failed == 0:
            return f"Task completed successfully with {successful} steps"
        elif successful > 0:
            return (
                f"Partial success: {successful} steps completed, {failed} steps failed"
            )
        else:
            return f"Task failed with {failed} failed steps"

    async def _call_llm_with_retry(
        self, messages: List[Dict[str, str]], **kwargs: Any
    ) -> Any:
        """Call LLM with retry mechanism: JSON mode first, then fallback to normal mode.

        This is similar to plan_generator._call_llm_with_retry and uses stream_chat().
        """
        try:
            # Clean messages before sending to LLM
            cleaned_messages = clean_messages(messages)

            # Use streaming API to collect complete response
            full_content = ""
            usage = {}

            # Prefer output_config over response_format for structured output
            if "output_config" in kwargs:
                # Use output_config (better for Gemini with complex schemas)
                output_config = kwargs.pop("output_config")
                async for chunk in self.llm.stream_chat(
                    messages=cleaned_messages,
                    output_config=output_config,
                    **kwargs,
                ):
                    if chunk.is_token():
                        full_content += chunk.delta
                    elif chunk.is_usage():
                        usage = chunk.usage
                    elif chunk.is_error():
                        raise RuntimeError(f"LLM stream error: {chunk.content}")
            else:
                # Fallback to response_format
                response_format = kwargs.pop("response_format", {"type": "json_object"})
                async for chunk in self.llm.stream_chat(
                    messages=cleaned_messages,
                    response_format=response_format,
                    **kwargs,
                ):
                    if chunk.is_token():
                        full_content += chunk.delta
                    elif chunk.is_usage():
                        usage = chunk.usage
                    elif chunk.is_error():
                        raise RuntimeError(f"LLM stream error: {chunk.content}")

            # Record token usage
            if usage:
                logger.info(
                    f"Goal check LLM usage - prompt_tokens: {usage.get('prompt_tokens', 0)}, "
                    f"completion_tokens: {usage.get('completion_tokens', 0)}, "
                    f"total_tokens: {usage.get('total_tokens', 0)}"
                )

                # Add token usage to tracker
                add_token_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=self.llm.model_name,
                    call_type="goal_check",
                )

            # Return format (compatible with original chat())
            # Ensure we always return a dict with content key
            if not isinstance(full_content, str):
                logger.error(
                    f"Unexpected full_content type: {type(full_content)}, value: {full_content!r}"
                )
                full_content = str(full_content)
            return {"content": full_content, "usage": usage}

        except Exception as e:
            logger.warning(f"JSON mode call failed, retrying with normal mode: {e}")

            # Fallback: Use streaming API to retry (without JSON mode)
            try:
                full_content = ""
                usage = {}

                # Preserve output_config if provided (for retry)
                output_config = kwargs.get("output_config")
                if output_config:
                    # Try with output_config first
                    async for chunk in self.llm.stream_chat(
                        messages=cleaned_messages,
                        output_config=output_config,
                        **kwargs,
                    ):
                        if chunk.is_token():
                            full_content += chunk.delta
                        elif chunk.is_usage():
                            usage = chunk.usage
                        elif chunk.is_error():
                            raise RuntimeError(f"LLM stream error: {chunk.content}")
                else:
                    # Fallback to no format constraints
                    async for chunk in self.llm.stream_chat(
                        messages=cleaned_messages,
                        **kwargs,
                    ):
                        if chunk.is_token():
                            full_content += chunk.delta
                        elif chunk.is_usage():
                            usage = chunk.usage
                        elif chunk.is_error():
                            raise RuntimeError(f"LLM stream error: {chunk.content}")

                logger.info(
                    f"Normal mode call succeeded (fallback), response length: {len(full_content)}"
                )

                # Record token usage for fallback
                if usage:
                    add_token_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=self.llm.model_name,
                        call_type="goal_check_fallback",
                    )

                # Ensure we always return a dict with content key
                if not isinstance(full_content, str):
                    logger.error(
                        f"Unexpected full_content type in fallback: {type(full_content)}, value: {full_content!r}"
                    )
                    full_content = str(full_content)
                return {"content": full_content, "usage": usage}

            except Exception as e2:
                logger.error(f"Normal mode call also failed: {e2}")
                raise
