"""
Plan generation logic for DAG plan-execute pattern.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ....model.chat.basic.base import BaseLLM
from ....model.chat.token_context import add_token_usage
from ....tools.adapters.vibe import Tool
from ...context import AgentContext
from ...exceptions import DAGPlanGenerationError, LLMResponseError
from ...trace import trace_dag_plan_end, trace_dag_plan_start
from ...utils.compact import CompactConfig, CompactUtils
from ...utils.llm_utils import clean_messages, extract_json_from_markdown
from .models import (
    ChatResponse,
    ExecutionPlan,
    Interaction,
    InteractionType,
    PlanGeneratorResult,
    PlanStep,
)
from .schemas import ClassificationResponse

logger = logging.getLogger(__name__)


class PlanGenerator:
    """Handles plan generation and extension logic"""

    # Common planning strategy guidelines
    _PLANNING_GUIDELINES = (
        "PLANNING STRATEGY GUIDELINES:\n"
        "- For tasks requiring MANY ITERATIONS (like browser automation, coding, complex problem-solving):\n"
        "  * Use fewer steps but provide each step with as MANY relevant tools as possible\n"
        "  * These tasks often require trial-and-error, multiple approaches, and dynamic adaptation\n"
        "  * Having comprehensive tools allows the step to iterate and refine without being blocked\n"
        "  * Examples: browser tools (click, type, scroll, screenshot, extract, wait), coding tools (write, execute, debug, test)\n"
        "- For DATA ANALYSIS tasks: Create logical phases (data collection, processing, analysis, reporting)\n"
        "- For SIMPLE TASKS: Prefer single steps with comprehensive tool sets over many fine-grained steps\n"
        "- Only break down tasks when they truly require dependency chains or different skill sets\n"
        "- PRINCIPLE: More tools in a step = greater flexibility and ability to handle iterative, complex work\n\n"
    )

    _PLANNING_EXAMPLE = (
        "Example:\n"
        "{\n"
        '  "plan": {\n'
        '    "steps": [\n'
        '      {"id": "step1", "name": "Research", "description": "Gather information", "tool_names": ["web_search"], "dependencies": [], "difficulty": "hard"},\n'
        '      {"id": "step2", "name": "Analyze Data", "description": "Analyze collected information", "tool_names": ["execute_python_code"], "dependencies": ["step1"], "difficulty": "hard"},\n'
        '      {"id": "step3", "name": "Organize Results", "description": "Summarize and format findings", "tool_names": [], "dependencies": ["step1", "step2"], "difficulty": "easy"}\n'
        "    ]\n"
        "  }\n"
        "}\n\n"
    )

    def __init__(
        self,
        llm: BaseLLM,
        fast_llm: Optional[BaseLLM] = None,
        skill_manager: Optional[Any] = None,
        allowed_skills: Optional[List[str]] = None,
    ):
        self.llm = llm
        self.fast_llm = fast_llm
        self.skill_manager = skill_manager
        self.allowed_skills = allowed_skills

    async def _generate_plan_with_flow(
        self,
        tracer: Any,
        goal: str,
        iteration: int,
        tools: List[Tool],
        history: List[Dict[str, Any]],
        prompt_builder_func: Any,
        is_extension: bool = False,
        current_plan: Optional[ExecutionPlan] = None,
        user_input_context: Optional[Dict[str, Any]] = None,
        context: Optional[AgentContext] = None,
        send_trace_event: bool = True,
        skill_context: Optional[str] = None,
    ) -> tuple[Optional[ExecutionPlan], List[PlanStep]]:
        """
        Execute the complete plan generation flow: start -> build prompt -> LLM -> parse -> validate -> end

        Returns:
            tuple: (execution_plan, additional_steps)
                For generation: execution_plan contains all steps, additional_steps is empty
                For extension: execution_plan is None, additional_steps contains new steps
        """
        # Send plan start event
        trace_task_id = (
            f"plan_extension_{uuid4()}" if is_extension else f"plan_{uuid4()}"
        )

        event_data = {
            "goal": goal,
            "iteration": iteration,
            "tools_count": len(tools),
            "history_length": len(history),
        }

        if is_extension:
            event_data.update(
                {
                    "extension": True,
                    "current_plan_id": current_plan.id if current_plan else None,
                    "current_steps_count": len(current_plan.steps)
                    if current_plan
                    else 0,
                    "user_input_context": user_input_context,
                }
            )

        if send_trace_event:
            await trace_dag_plan_start(tracer, trace_task_id, data=event_data)

        try:
            # skill_context is now pre-fetched and passed in from caller
            # This allows parallel execution with memory lookup
            pass

            # Build prompt using provided function
            if is_extension:
                prompt = prompt_builder_func(
                    goal,
                    iteration,
                    history,
                    current_plan,
                    user_input_context,
                    tools,
                    context,
                )
            else:
                prompt = prompt_builder_func(
                    goal, iteration, history, tools, context, skill_context
                )

            # Call LLM
            logger.info(
                f"Calling LLM for {'plan extension' if is_extension else 'planning'}, prompt: {prompt}"
            )
            response = await self._call_llm_with_retry(messages=prompt)

            content = response["content"] if isinstance(response, dict) else response
            logger.info(f"LLM response received, length: {len(str(content))}")

            # Parse response with retry mechanism
            error_context = None
            max_validation_retries = 2

            for validation_attempt in range(max_validation_retries + 1):
                try:
                    # For first attempt, use normal parsing. For retries, parse with error context.
                    if validation_attempt == 0:
                        parsed_data = await self._parse_plan_response_with_retry(
                            content, prompt, error_context=None
                        )
                    else:
                        parsed_data = await self._parse_plan_response_with_retry(
                            content, prompt, error_context=error_context
                        )

                    steps_data = parsed_data.get("steps", [])
                    task_name = parsed_data.get("task_name")

                    if not steps_data:
                        if is_extension:
                            logger.info(
                                "No additional steps generated for plan extension - LLM returned empty plan"
                            )
                            return None, []
                        else:
                            raise LLMResponseError(
                                "Failed to parse plan response from LLM",
                                response=content,
                                expected_format="JSON object with plan field containing steps array",
                                context={"iteration": iteration, "goal": goal[:100]},
                            )

                    # Create PlanStep objects and validate for first attempt
                    if is_extension:
                        # For extension, we need to handle existing step IDs
                        existing_step_ids = (
                            {step.id for step in current_plan.steps}
                            if current_plan
                            else set()
                        )
                        additional_steps = []

                        for step_data in steps_data:
                            step_id = step_data.get("id", str(uuid4()))
                            # Ensure unique step ID
                            while step_id in existing_step_ids:
                                step_id = str(uuid4())
                            existing_step_ids.add(step_id)

                            step = PlanStep(
                                id=step_id,
                                name=step_data["name"],
                                description=step_data["description"],
                                tool_names=step_data.get("tool_names", []),
                                dependencies=step_data.get("dependencies", []),
                                difficulty=step_data.get("difficulty", "hard"),
                                conditional_branches=step_data.get(
                                    "conditional_branches", {}
                                ),
                                required_branch=step_data.get("required_branch"),
                            )
                            additional_steps.append(step)

                        # Validate dependencies (both existing and new steps)
                        all_step_ids = existing_step_ids.copy()
                        for step in additional_steps:
                            all_step_ids.add(step.id)

                        for step in additional_steps:
                            invalid_deps = [
                                dep
                                for dep in step.dependencies
                                if dep not in all_step_ids
                            ]
                            if invalid_deps:
                                logger.warning(
                                    f"New step {step.id} has invalid dependencies: {invalid_deps}"
                                )
                                step.dependencies = [
                                    dep
                                    for dep in step.dependencies
                                    if dep in all_step_ids
                                ]

                        # Validate tool references for the new steps
                        self._validate_steps_tools(additional_steps, tools)

                        # Send trace event for extension
                        plan_data = {
                            "id": current_plan.id if current_plan else "unknown",
                            "goal": goal,
                            "task_name": task_name,  # Include task_name in trace event
                            "steps": [
                                {
                                    "id": step.id,
                                    "name": step.name,
                                    "description": step.description,
                                    "tool_names": step.tool_names,
                                    "dependencies": step.dependencies,
                                    "status": step.status.value
                                    if hasattr(step.status, "value")
                                    else str(step.status),
                                    "conditional_branches": step.conditional_branches,
                                    "required_branch": step.required_branch,
                                    "is_conditional": step.is_conditional,
                                }
                                for step in additional_steps
                            ],
                        }

                        if send_trace_event:
                            await trace_dag_plan_end(
                                tracer,
                                trace_task_id,
                                data={
                                    "steps_count": len(additional_steps),
                                    "plan_id": current_plan.id
                                    if current_plan
                                    else "unknown",
                                    "plan_data": plan_data,
                                    "extension": True,
                                },
                            )

                        return None, additional_steps
                    else:
                        # For generation, create all steps
                        steps = []
                        step_ids = set()

                        for step_data in steps_data:
                            step_id = step_data.get("id", str(uuid4()))
                            step_ids.add(step_id)

                            step = PlanStep(
                                id=step_id,
                                name=step_data["name"],
                                description=step_data["description"],
                                tool_names=step_data.get("tool_names", []),
                                dependencies=step_data.get("dependencies", []),
                                difficulty=step_data.get("difficulty", "hard"),
                                conditional_branches=step_data.get(
                                    "conditional_branches", {}
                                ),
                                required_branch=step_data.get("required_branch"),
                            )
                            steps.append(step)

                        # Validate dependencies
                        for step in steps:
                            invalid_deps = [
                                dep for dep in step.dependencies if dep not in step_ids
                            ]
                            if invalid_deps:
                                logger.warning(
                                    f"Step {step.id} has invalid dependencies: {invalid_deps}"
                                )
                                step.dependencies = [
                                    dep for dep in step.dependencies if dep in step_ids
                                ]

                        # Create execution plan
                        plan = ExecutionPlan(
                            id=str(uuid4()),
                            goal=goal,
                            steps=steps,
                            iteration=iteration,
                            task_name=task_name,  # Add task_name for display
                        )

                        # Validate the generated plan - this can raise DAGPlanGenerationError
                        self._validate_plan(plan, tools)

                        # Prepare plan data for trace event
                        plan_data = {
                            "id": plan.id,
                            "goal": goal,
                            "task_name": task_name,  # Include task_name in trace event
                            "steps": [
                                {
                                    "id": step.id,
                                    "name": step.name,
                                    "description": step.description,
                                    "tool_names": step.tool_names,
                                    "dependencies": step.dependencies,
                                    "status": step.status.value
                                    if hasattr(step.status, "value")
                                    else str(step.status),
                                    "conditional_branches": step.conditional_branches,
                                    "required_branch": step.required_branch,
                                    "is_conditional": step.is_conditional,
                                }
                                for step in steps
                            ],
                        }

                        # Send trace event for generation
                        if send_trace_event:
                            await trace_dag_plan_end(
                                tracer,
                                trace_task_id,
                                data={
                                    "steps_count": len(steps),
                                    "plan_id": plan.id,
                                    "plan_data": plan_data,
                                },
                            )

                        return plan, []

                except DAGPlanGenerationError as e:
                    if validation_attempt < max_validation_retries:
                        logger.warning(
                            f"Plan validation failed (attempt {validation_attempt + 1}/{max_validation_retries + 1}): {e}. Retrying with error context..."
                        )

                        # Build error context for retry
                        available_tools = set()
                        available_tools_list = []
                        for tool in tools:
                            tool_name = None
                            if hasattr(tool, "metadata") and hasattr(
                                tool.metadata, "name"
                            ):
                                tool_name = tool.metadata.name
                            elif hasattr(tool, "name"):
                                tool_name = tool.name

                            if tool_name and tool_name not in available_tools:
                                available_tools.add(tool_name)
                                available_tools_list.append(tool_name)

                        error_context = {
                            "error_type": "DAGPlanGenerationError",
                            "error_message": str(e),
                            "missing_tools": e.context.get("missing_tools", [])
                            if e.context
                            else [],
                            "available_tools": available_tools_list,
                        }

                        # Need to regenerate content with error context, so call LLM again
                        # Add error context to the messages for retry
                        missing_tools = (
                            e.context.get("missing_tools", []) if e.context else []
                        )
                        retry_messages = clean_messages(prompt) + [
                            {
                                "role": "user",
                                "content": f"\n\nPREVIOUS ERROR INFORMATION:\n"
                                f"Error Type: DAGPlanGenerationError\n"
                                f"Error Message: {str(e)}\n"
                                f"Missing Tools: {', '.join(missing_tools)}\n\n"
                                f"Available Tools:\n"
                                f"{', '.join(available_tools_list)}\n\n"
                                f"COMMON TOOL NAMING MISTAKES TO AVOID:\n"
                                f"- Use 'write_file' NOT 'write__file' (single underscore, not double)\n"
                                f"- Use 'read_file' NOT 'read__file'\n"
                                f"- Do NOT add any prefixes or suffixes to tool names\n"
                                f"- Do NOT invent tools that are not in the Available Tools list\n\n"
                                f"Please correct your plan by:\n"
                                f"1. Removing references to non-existent tools: {', '.join(missing_tools)}\n"
                                f"2. Using only tools from the Available Tools list above\n"
                                f"3. If you need functionality not covered by available tools, break the task into simpler steps that can use available tools\n\n"
                                f"Retry your plan generation with correct tool names.",
                            }
                        ]

                        # Call LLM again with error context
                        response = await self._call_llm_with_retry(
                            messages=retry_messages
                        )
                        content = (
                            response["content"]
                            if isinstance(response, dict)
                            else response
                        )

                        # Continue to next iteration to retry parsing and validation
                        continue
                    else:
                        # Max retries reached, re-raise the exception
                        logger.error(
                            f"Plan validation failed after {max_validation_retries + 1} attempts: {e}"
                        )
                        raise

        except Exception as e:
            if isinstance(e, (LLMResponseError, DAGPlanGenerationError)):
                raise
            else:
                logger.error(
                    f"Error in {'plan extension' if is_extension else 'plan generation'}: {e}"
                )
                if is_extension:
                    raise DAGPlanGenerationError(
                        f"Plan extension failed: {str(e)}",
                        goal=goal,
                        iteration=iteration,
                        llm_response=str(response) if "response" in locals() else None,
                        context={"goal": goal[:100], "tools_count": len(tools)},
                        cause=e,
                    )
                else:
                    raise DAGPlanGenerationError(
                        f"Plan generation failed: {str(e)}",
                        goal=goal,
                        iteration=iteration,
                        llm_response=str(response) if "response" in locals() else None,
                        context={"goal": goal[:100], "tools_count": len(tools)},
                        cause=e,
                    )

        # This should never be reached due to proper exception handling and early returns
        # but satisfies mypy's control flow analysis
        raise DAGPlanGenerationError(
            "Unexpected execution path in plan generation",
            goal=goal,
            iteration=iteration,
            context={"goal": goal[:100], "tools_count": len(tools)},
        )

    async def should_chat_directly(
        self,
        goal: str,
        tools: List[Tool],
        iteration: int,
        history: List[Dict[str, Any]],
        tracer: Any,
        context: Optional[AgentContext] = None,
    ) -> PlanGeneratorResult:
        """
        Quick check if the goal can be answered directly without planning.

        Returns:
            PlanGeneratorResult with type="chat" and chat_response if should chat
            PlanGeneratorResult with type="plan" (no plan object) if should generate plan

        This is called BEFORE skill selection to quickly determine the execution path.
        """
        logger.info(f"[should_chat_directly] Checking goal: {goal[:100]}")
        logger.info(
            f"[should_chat_directly] Context: history_count={len(history)}, tools_count={len(tools)}, iteration={iteration}"
        )
        if context:
            logger.info(
                f"[should_chat_directly] Agent context: {type(context).__name__}"
            )
            # Log context state for debugging
            if hasattr(context, "state"):
                logger.info(
                    f"[should_chat_directly] Context state keys: {list(context.state.keys())}"
                )
                if "system_prompt" in context.state:
                    logger.info(
                        f"[should_chat_directly] System prompt in context: {context.state['system_prompt'][:200]}..."
                    )
                if "file_info" in context.state:
                    logger.info(
                        f"[should_chat_directly] File info in context: {context.state['file_info']}"
                    )
                if "uploaded_files" in context.state:
                    logger.info(
                        f"[should_chat_directly] Uploaded files in context: {context.state['uploaded_files']}"
                    )

        # Build classification prompt (no skill context needed for quick check)
        messages = self._build_classification_prompt(
            goal, history, tools, context, skill_context=None
        )
        logger.info(
            f"[should_chat_directly] Built prompt with {len(messages)} messages"
        )

        # Call LLM to analyze
        try:
            # Prepare output_config with JSON schema from Pydantic model
            # This ensures the required fields are present and provides type safety
            # Note: ClaudeLLM will automatically fix the schema for API compatibility
            output_config = {
                "format": {
                    "type": "json_schema",
                    "schema": ClassificationResponse.model_json_schema(),
                }
            }

            response = await self._call_llm_with_retry(
                messages=messages, output_config=output_config
            )

            content = response["content"] if isinstance(response, dict) else response
            usage = response.get("usage") if isinstance(response, dict) else None

            # Record token usage
            if usage:
                logger.info(
                    f"[should_chat_directly] LLM usage - "
                    f"prompt_tokens: {usage.get('prompt_tokens', 0)}, "
                    f"completion_tokens: {usage.get('completion_tokens', 0)}, "
                    f"total_tokens: {usage.get('total_tokens', 0)}"
                )

            logger.info(f"LLM analysis response received, length: {len(str(content))}")

            # Log raw response for debugging parsing issues
            logger.debug(f"Raw LLM response: {str(content)[:500]}")

            # Try to parse as JSON
            try:
                json_str = extract_json_from_markdown(content)
                parsed = json.loads(json_str)

                if not isinstance(parsed, dict):
                    raise ValueError("Response is not a dictionary")

                response_type = parsed.get("type", "")

                if response_type == "chat":
                    # Parse chat response
                    chat_data = parsed.get("chat", {})
                    message = chat_data.get("message", "")

                    interactions = []
                    for interaction_data in chat_data.get("interactions", []):
                        interaction_type = InteractionType(
                            interaction_data.get("type", "text_input")
                        )
                        interaction = Interaction(
                            type=interaction_type,
                            field=interaction_data.get("field"),
                            label=interaction_data.get("label"),
                            options=interaction_data.get("options"),
                            placeholder=interaction_data.get("placeholder"),
                            multiline=interaction_data.get("multiline"),
                            min=interaction_data.get("min"),
                            max=interaction_data.get("max"),
                            default=interaction_data.get("default"),
                            accept=interaction_data.get("accept"),
                            multiple=interaction_data.get("multiple"),
                        )
                        interactions.append(interaction)

                    chat_response = ChatResponse(
                        message=message,
                        interactions=interactions if interactions else None,
                    )

                    return PlanGeneratorResult(type="chat", chat_response=chat_response)

                elif response_type == "plan":
                    # Need to generate plan
                    return PlanGeneratorResult(type="plan", plan=None)

                else:
                    # Unknown type, assume plan generation is needed
                    logger.info(
                        f"Unknown response type '{response_type}', treating as plan"
                    )
                    return PlanGeneratorResult(type="plan", plan=None)

            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"Failed to parse LLM response as structured JSON: {e}")
                # On parse error, assume plan is needed
                return PlanGeneratorResult(type="plan", plan=None)

        except Exception as e:
            logger.error(f"Error during analysis: {e}")
            # On error, assume plan is needed
            return PlanGeneratorResult(type="plan", plan=None)

    def _build_tools_context(self, tools: List[Tool]) -> str:
        """
        Build tools context with new format: tool list + detailed descriptions + collaboration examples.

        Args:
            tools: List of available tools

        Returns:
            Formatted tools context string
        """
        if not tools:
            return ""

        # Collect tool information
        tool_info_list = []
        tool_names = []

        for tool in tools:
            if tool.metadata:
                tool_name = tool.metadata.name
                tool_description = tool.metadata.description or f"Execute {tool_name}"
            else:
                tool_name = getattr(tool, "name", "unknown_tool")
                tool_description = getattr(tool, "description", f"Execute {tool_name}")

            tool_names.append(tool_name)
            tool_info_list.append((tool_name, tool_description))

        # Build the new format
        context_parts = []

        # Part 1: Tool name list
        context_parts.append("AVAILABLE TOOLS:\n")
        context_parts.append(", ".join(tool_names) + "\n")

        # Part 2: Detailed descriptions (by tool)
        # Note: We keep descriptions concise in plan phase to focus on strategy,
        # not implementation details. Parameter schemas are only shown in execute phase.
        context_parts.append("TOOL DESCRIPTIONS:\n\n")
        for tool_name, tool_description in tool_info_list:
            context_parts.append(f"{tool_name}:\n  {tool_description}\n\n")

        # Part 3: Collaboration examples
        has_browser = any("browser" in name.lower() for name in tool_names)
        has_vision = any(
            "vision" in name.lower() or "understand_images" in name.lower()
            for name in tool_names
        )

        if has_browser and has_vision:
            context_parts.append("COLLABORATION EXAMPLES:\n\n")
            context_parts.append(
                "Web Page Visual Modification:\n"
                "1. browser_screenshot - capture current page\n"
                "2. vision tools - analyze screenshot content\n"
                "3. browser_evaluate - make targeted modifications\n"
            )

        return "".join(context_parts)

    def _build_data_production_execution_policy(self, tools: List[Tool]) -> str:
        """构造“造数专用系统”分类提示词。

        这个方法专门约束 `should_chat_directly()` 的第一阶段分类行为。
        当前系统里最容易出现的误判是：
        - 模型明明拿到了 HTTP/SQL/KB/skills/MCP 这类专业工具
        - 却在分类阶段直接返回 `type="chat"`
        - 然后用“信息不足”“无法访问系统”“请先补充背景”来跳过执行链

        对造数系统来说，这种行为是错误的，因为正确顺序应该是：
        1. 先进入执行链
        2. 先查询可用资产/知识
        3. 再根据检索结果判断是否还缺精确参数
        """
        tool_names: set[str] = set()
        has_mcp_tools = False

        for tool in tools:
            metadata = getattr(tool, "metadata", None)
            if metadata is not None:
                tool_names.add(str(metadata.name))
                has_mcp_tools = has_mcp_tools or str(metadata.category.value) == "mcp"
            else:
                tool_names.add(str(getattr(tool, "name", "unknown_tool")))

        discovery_rules: list[str] = []
        # 规划阶段也必须同步同一套 HTTP 路由边界。
        #
        # 否则会出现一种很隐蔽的问题：
        # - ReAct 执行阶段知道“明确 endpoint 应走 api_call”
        # - 但 DAG 规划阶段仍把所有 HTTP 请求都规划成资产查询流
        #
        # 结果就是不同执行模式下，同一句用户话术会走不同工具。
        if "api_call" in tool_names:
            discovery_rules.append(
                "- If the user already specifies a concrete URL, endpoint, curl snippet, OpenAPI path, or asks to call a designated HTTP API directly, prefer execution mode so `api_call` can be used directly."
            )
        if "query_http_resource" in tool_names:
            discovery_rules.append(
                "- Use execution mode to query HTTP assets only when the user needs an internal managed HTTP capability but has not specified a concrete endpoint yet."
            )
        if "execute_http_resource" in tool_names:
            discovery_rules.append(
                "- Use execute_http_resource only after a managed HTTP asset is identified; it is not the default path for arbitrary direct API calls."
            )
        if "query_vanna_sql_asset" in tool_names:
            discovery_rules.append(
                "- 在断言目标数据/报表无法产出之前，先进入执行模式查询 SQL assets。"
            )
        if "knowledge_search" in tool_names or "list_knowledge_bases" in tool_names:
            discovery_rules.append(
                "- 回答内部业务问题前，先进入执行模式检查/搜索知识库，而不是直接依赖内置知识。"
            )
        if "read_skill_doc" in tool_names or "list_skill_docs" in tool_names:
            discovery_rules.append(
                "- 在声称流程或能力受限之前，先进入执行模式检查 skill 文档。"
            )
        if has_mcp_tools:
            discovery_rules.append(
                "- 如果已连接的 MCP 工具可能有帮助，优先进入执行模式，而不是直接聊天，让运行时先检查并使用这些能力。"
            )

        if not discovery_rules:
            return ""

        return (
            "\n## 专用造数策略\n"
            "- 你当前运行在专用的内部造数系统中，而不是通用聊天机器人。\n"
            "- 如果请求可能依赖内部业务数据、开户流程、环境操作、HTTP/API 资源、SQL assets、知识库、skills 或 MCP 连接系统，你必须返回 `{\\\"type\\\": \\\"plan\\\"}`。\n"
            "- 不要仅仅因为参数不完整、暂时不确定该用哪个 asset，或者你以为自己无法访问内部系统，就返回 `type=\\\"chat\\\"`。\n"
            "- 执行阶段的存在，就是为了先检查资产，再在必要时追问精确缺失参数。\n"
            "- 只有当请求是纯粹的普通对话，或者无需任何内部工具、资产、知识检索就能完整回答时，才使用 `type=\\\"chat\\\"`。\n"
            + "\n".join(discovery_rules)
            + "\n"
        )

    def _build_classification_prompt(
        self,
        goal: str,
        history: List[Dict[str, Any]],
        tools: List[Tool],
        context: Optional[AgentContext] = None,
        skill_context: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build prompt for classifying user input (chat vs plan)"""
        logger.debug(
            f"[_build_classification_prompt] Building prompt with {len(history)} history items, {len(tools)} tools"
        )

        # Check if custom system prompt is provided in context (e.g., file information)
        custom_prompt = ""
        if (
            context
            and hasattr(context, "state")
            and "system_prompt" in context.state
            and context.state["system_prompt"]
        ):
            custom_prompt = context.state["system_prompt"]
            logger.info(
                f"[_build_classification_prompt] Using custom system prompt from context: {custom_prompt[:100]}..."
            )

        # Build tools context with new format
        tools_context = ""
        if tools:
            tools_context = self._build_tools_context(tools)
        specialized_policy = self._build_data_production_execution_policy(tools)

        # Build system prompt
        system_prompt = (
            custom_prompt
            + """你是一个智能任务助手。分析用户的输入并决定：

1. **直接回答（type: "chat"）** - 如果用户问一个简单问题，你可以直接回答而无需执行任何任务
2. **需要澄清（type: "chat"）** - 如果你需要更多信息来有效帮助用户
3. **需要执行（type: "plan"）** - 如果用户的请求需要多步骤工具执行

## 响应格式

### 对于聊天（直接回答或澄清）：
```json
{
  "type": "chat",
  "chat": {
    "message": "你对用户的回复",
    "interactions": [
      {
        "type": "select_one|select_multiple|text_input|file_upload|confirm|number_input",
        "field": "field_name",
        "label": "显示标签",
        "options": [{"value": "A", "label": "选项 A"}],
        "placeholder": "...",
        "multiline": false,
        "min": 1,
        "max": 100,
        "default": true,
        "accept": [".csv", ".xlsx"],
        "multiple": false
      }
    ]
  }
}
```

### 对于计划（需要执行 - 只需表明这一点，不要生成计划）：
```json
{
  "type": "plan"
}
```

## 交互类型
- **select_one**: 单选
- **select_multiple**: 多选
- **text_input**: 单行文本输入
- **file_upload**: 带类型限制的文件上传
- **confirm**: 是/否确认
- **number_input**: 带最小/最大值的数字输入

文件引用：
- 你可能会看到格式为 [filename](file://fileId) 的文件引用
- 被引用的文件可能不在当前工作区中
- 'fileId' 部分是读取文件的唯一有效标识符
- 如果用户提供了文件引用，他们可能希望你处理它（这通常意味着 type="plan"）

## 重要指南
- 对所有文本使用与用户目标相同的语言
- 仅在明显需要多步骤工具执行时使用 "plan" 类型
- 对于简单问题、澄清或信息收集，使用 "chat" 类型
- 当返回 type="plan" 时，不要包含计划详情 - 只需类型指示器
- interactions 是可选的 - 如果不需要用户输入则省略

## 关键：直接聊天模式指南
当你返回 type="chat"（直接回答模式）时，你只提供文本响应。不会执行任何工具。
- **不要**描述你"将要做"、"打算做"或"开始做"什么
- **不要**使用"Now starting to..."、"Next I will..."、"Let me begin..."等短语
- **不要**承诺未来动作或描述执行步骤
- **要**提供直接、即时的答案回应用户的问题
- **要**提供有用信息、解释或直接问澄清问题
- 记住：type="chat" 意味着对话，不是执行。用户看到的是你的最终回复，而不是行动计划。

## 关键：文件和媒体处理规则
- **如果用户上传了图片、视频、音频或其他媒体文件**：你必须使用 type="plan" 来执行工具。你不能在聊天模式下分析媒体。
- **如果用户上传了 PDF、文档或其他文件**：你必须使用 type="plan" 用工具读取和处理它们。
- **不要**在聊天模式下猜测、幻觉或假设文件内容
- **不要**描述你"认为"可能在图片或文件中的内容，而不要实际使用工具检查
- **如果你看到文件名但无法访问其内容**：始终使用 type="plan"
- **记住**：你只能通过计划模式下的工具读取文件和分析图片
"""
        )

        if tools_context:
            system_prompt += f"\n{tools_context}\n"
        if specialized_policy:
            system_prompt += f"\n{specialized_policy}\n"

        # Build messages list with history
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history as separate messages
        if history:
            messages.extend(history)

        # Add current goal as the final user message
        messages.append(
            {
                "role": "user",
                "content": f"用户输入：{goal}\n\n请结合以上规则，返回合适的 JSON 响应。",
            }
        )

        return messages

    async def generate_plan(
        self,
        goal: str,
        tools: List[Tool],
        iteration: int,
        history: List[Dict[str, Any]],
        tracer: Any,
        context: Optional[AgentContext] = None,
        skill_context: Optional[str] = None,
    ) -> ExecutionPlan:
        """
        Generate a DAG-structured execution plan

        Raises:
            DAGPlanGenerationError: When plan generation fails
            LLMResponseError: When LLM response is invalid
        """
        logger.info(f"Generating plan for iteration {iteration}")

        # Use the unified plan generation flow
        # Note: We don't send trace events here, letting the caller (dag_plan_execute.py) manage them
        plan, _ = await self._generate_plan_with_flow(
            tracer=tracer,
            goal=goal,
            iteration=iteration,
            tools=tools,
            history=history,
            prompt_builder_func=self._build_planning_prompt,
            is_extension=False,
            context=context,
            send_trace_event=False,  # Don't send trace events, caller will manage
            skill_context=skill_context,  # Pass pre-fetched skill context
        )

        # For plan generation (is_extension=False), plan should never be None
        assert plan is not None, "Plan generation should never return None"

        # Validate the generated plan
        self._validate_plan(plan, tools)

        return plan

    async def extend_plan(
        self,
        goal: str,
        tools: List[Tool],
        iteration: int,
        history: List[Dict[str, Any]],
        current_plan: ExecutionPlan,
        tracer: Any,
        user_input_context: Optional[Dict[str, Any]] = None,
        context: Optional[AgentContext] = None,
    ) -> List[PlanStep]:
        """Extend existing plan with additional steps (maintains immutability)"""
        logger.info(f"Extending plan for iteration {iteration}")

        # Use the unified plan generation flow
        _, additional_steps = await self._generate_plan_with_flow(
            tracer=tracer,
            goal=goal,
            iteration=iteration,
            tools=tools,
            history=history,
            prompt_builder_func=self._build_plan_extension_prompt,
            is_extension=True,
            current_plan=current_plan,
            user_input_context=user_input_context,
            context=context,
        )

        return additional_steps

    def _build_plan_extension_prompt(
        self,
        goal: str,
        iteration: int,
        history: List[Dict[str, Any]],
        current_plan: ExecutionPlan,
        user_input_context: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Tool]] = None,
        context: Optional[AgentContext] = None,
    ) -> List[Dict[str, str]]:
        """Build prompt for extending existing plan with additional steps"""

        history_context = ""
        if history:
            # Convert history to messages format for compacting
            history_messages = [
                {"role": "user", "content": json.dumps(iteration_data, default=str)}
                for iteration_data in history
            ]

            # Use CompactUtils.truncate_messages with default config
            max_messages = CompactConfig().fallback_truncate_count
            history_messages = CompactUtils.truncate_messages(
                history_messages, max_messages=max_messages
            )

            # Convert back to JSON string
            history_str = "\n".join([msg["content"] for msg in history_messages])
            history_context = f"\nPrevious execution history:\n{history_str}\n"

        # Get current plan summary
        current_steps_summary = []
        for step in current_plan.steps:
            status_emoji = (
                "⏳"
                if step.status.value == "pending"
                else "✅"
                if step.status.value == "completed"
                else "❌"
            )
            desc_preview = step.description[:100] + (
                "..." if len(step.description) > 100 else ""
            )
            current_steps_summary.append(
                f"{status_emoji} {step.id}: {step.name}\n   说明：{desc_preview}\n   状态：{step.status.value}"
            )

        current_plan_context = "\n当前计划步骤：\n" + "\n\n".join(
            current_steps_summary
        )

        # Check if custom system prompt is provided in context
        custom_prompt = ""
        if (
            context
            and hasattr(context, "state")
            and "system_prompt" in context.state
            and context.state["system_prompt"]
        ):
            custom_prompt = f"\n\n{context.state['system_prompt']}\n\n"

        # Build tools context with new format
        tools_context = ""
        if tools:
            tools_context = self._build_tools_context(tools)
        else:
            tools_context = "\n\n注意：当前没有可用工具。请生成仍然有助于达成目标的额外概念步骤，并为每个步骤使用合适的假设性 tool 名称。"

        system_prompt = custom_prompt + (
            "你是一个负责扩展既有执行计划的 AI 规划助手。\n"
            "当前计划已经创建完成，并且其中部分步骤可能已经执行。\n"
            "你的任务是补充为达成目标仍然需要的额外步骤。\n"
            "你不能修改、重建或覆盖已有步骤，只能新增步骤。\n"
            "新增步骤可以依赖已有步骤，也可以依赖其他新增步骤。\n\n"
            "重要：当出现新的用户请求时：\n"
            "- 仔细检查所有仍处于 PENDING 状态（标记为 ⏳）的步骤及其描述\n"
            "- 判断这些待执行步骤的描述是否仍与新的用户需求一致\n"
            "- 如果待执行步骤未来产生的结果会与新请求冲突，就新增步骤去修正或补偿这些结果\n"
            "- 记住：待执行步骤本身不能被修改，因此必要时你必须增加补偿步骤\n\n"
            f"你可以在计划步骤中使用以下工具：{tools_context}\n\n"
            f"{self._PLANNING_GUIDELINES}"
            "难度评估：你必须为每个新增步骤评估 difficulty：\n"
            "- 'easy'：可以快速完成的简单任务，例如基础搜索、简单计算、直接分析\n"
            "- 'hard'：需要深入思考、复杂问题拆解或大量处理的任务\n\n"
            "只返回新增步骤对应的合法 JSON。"
            f"{self._PLANNING_EXAMPLE}"
        )

        logger.debug(f"PLAN EXTENSION SYSTEM PROMPT:\n{system_prompt}")

        user_prompt = (
            f"目标：{goal}\n"
            f"迭代轮次：{iteration}\n"
            f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{current_plan_context}\n"
            f"{history_context}"
        )

        # Add new user input if provided
        if user_input_context and "new_input" in user_input_context:
            new_input = user_input_context["new_input"]
            user_prompt += f"\n{'=' * 80}\n"
            user_prompt += f"新的用户请求：{new_input}\n"
            user_prompt += f"{'=' * 80}\n"
            user_prompt += "用户补充了新的要求或修改。\n"
            user_prompt += "请回看上面的 PENDING 步骤；如果它们的描述与该请求冲突，就新增步骤来处理。\n"

            # Add file information if available
            if "uploaded_files" in user_input_context:
                uploaded_files = user_input_context["uploaded_files"]
                file_info = user_input_context.get("file_info", [])
                user_prompt += f"\n已上传文件：共有 {len(uploaded_files)} 个文件可处理：\n"
                for f in file_info:
                    file_name = f.get("name", "unknown")
                    file_size = f.get("size", 0)
                    file_type = f.get("type", "unknown")
                    user_prompt += f"- {file_name} ({file_size} bytes, {file_type})\n"
                user_prompt += "这些文件已经上传，并且可在 workspace 中使用。\n"
                user_prompt += "规划额外步骤时，请把这些文件纳入考虑。\n"
        else:
            user_prompt += "请根据执行结果和当前计划，判断还需要补充哪些额外步骤才能达成目标。\n"

        user_prompt += (
            "请以 JSON 对象返回额外步骤，结构为包含 `plan.steps` 数组。每个 step 必须包含：\n"
            "- id：唯一标识符（string，且不能与现有 step ID 重复）\n"
            "- name：步骤名称（string）\n"
            "- description：步骤要做的事情（string）\n"
            "- tool_names：该步骤可用的工具列表（string 数组，可以为空）\n"
            "- dependencies：该步骤依赖的 step ID 列表（string 数组）\n"
            "- difficulty：`easy` 或 `hard`\n"
            "关键依赖规则：\n"
            "- 你只能依赖上方 `Current plan steps` 中已经列出的 step ID\n"
            "- 你不能依赖不存在的 step ID，也不能依赖你这次响应里新创建的 step ID\n"
            "- 如果你需要多个新增步骤互相依赖，先先让它们不带 dependencies 创建出来\n"
            "- 非法 dependencies 会被自动移除，并且可能导致执行问题\n\n"
            "格式：\n"
            "{\n"
            '  "plan": {\n'
            '    "goal": "在这里重复原始目标",\n'
            '    "steps": [\n'
            "      // 在这里放 step 对象\n"
            "    ]\n"
            "  }\n"
            "}\n\n"
            '如果不需要额外步骤，就返回空 steps 数组，例如：{"plan": {"goal": "goal here", "steps": []}}\n'
            "只返回 JSON 对象，不要附加其他说明文字。"
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _build_skill_context(self, skill: Dict[str, Any]) -> str:
        """Build skill context string from skill info"""
        # Use the complete SKILL.md content directly
        content = skill.get("content", "")

        return f"## 🧰 Available Skill: {skill['name']}\n\n{content}"

    def _build_planning_prompt(
        self,
        goal: str,
        iteration: int,
        history: List[Dict[str, Any]],
        tools: List[Tool],
        context: Optional[AgentContext] = None,
        skill_context: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build prompt for plan generation"""

        # Check if custom system prompt is provided in context
        custom_prompt = ""
        use_custom_role = False
        if (
            context
            and hasattr(context, "state")
            and "system_prompt" in context.state
            and context.state["system_prompt"]
        ):
            # User's instruction replaces the default role "You are an AI planning assistant..."
            # But keeps the planning capability description
            custom_prompt = context.state["system_prompt"]
            use_custom_role = True

        # Build tools context with new format
        tools_context = ""
        if tools:
            tools_context = self._build_tools_context(tools)
        else:
            tools_context = "\n\nNote: No tools are currently available. Please generate a conceptual execution plan that breaks down the task into logical steps. Use hypothetical tool names that would be appropriate for each step (e.g., 'data_analyzer', 'report_generator', etc.). Each step should be executable conceptually even without actual tools.\n"

        # Build system prompt with role or custom instruction
        if use_custom_role:
            # Use user's instruction as role, then add planning capability
            system_prompt = (
                custom_prompt
                + "\n\n"
                + (
                    "使用规划能力将任务分解为多个步骤。\n"
                    "将计划创建为 DAG（有向无环图），其中步骤之间可以存在依赖关系。\n"
                    "每个步骤需要指定它依赖于哪些前序步骤。\n"
                    "没有依赖关系的步骤可以并行执行。\n"
                    f"你可以在计划步骤中使用以下工具：\n{tools_context}\n"
                )
            )
        else:
            # Use default role
            system_prompt = custom_prompt + (
                "你是一个 AI 规划助手，负责创建详细的执行计划。\n"
                "将计划创建为 DAG（有向无环图），其中步骤之间可以存在依赖关系。\n"
                "每个步骤需要指定它依赖于哪些前序步骤。\n"
                "没有依赖关系的步骤可以并行执行。\n"
                f"你可以在计划步骤中使用以下工具：\n{tools_context}\n"
            )

        # Add skill context if available
        if skill_context:
            system_prompt += (
                "\n" + skill_context + "\n\n"
                "重要提示：上方提供了一个技能，包含领域知识和模板。"
                "利用该技能的知识和模板来提升计划的质量和相关性。\n"
            )

        system_prompt += (
            "重要提示：并非每个步骤都需要使用工具。有些步骤可以是纯分析或组织任务。\n"
            "- 以下场景使用工具：网络搜索、计算、代码执行、数据处理\n"
            "- 对于纯分析任务（总结、组织、解释、格式化结果）：将 tool_name 设置为 null 或空字符串\n\n"
            "文件引用：\n"
            "- 你可能会看到格式为 [filename](file://fileId) 的文件引用\n"
            "- 被引用的文件可能不在当前工作区中。\n"
            "- 'fileId' 部分是读取文件的唯一有效标识符。\n"
            "- 使用工具读取文件时，直接传递 fileId。\n"
            "- 示例：如果你看到 [data.csv](file://123)，使用 '123' 来读取文件。\n\n"
            "条件分支：\n"
            "- 某些步骤可以是条件节点，根据运行时条件分支执行路径\n"
            "- 使用 'conditional_branches' 字段将步骤定义为条件节点\n"
            '- 格式：{"branch_key": "next_step_id"}\n'
            "- 示例：一个检查是否需要人工协助的步骤可能包含：\n"
            '  conditional_branches: {"human": "human_response_step", "kb": "knowledge_base_step"}\n'
            "- 条件节点必须返回一个分支键（如 'human' 或 'kb'）作为其最终答案\n"
            "- 依赖于条件节点的步骤应使用 'required_branch' 来指定它们属于哪个分支\n"
            '- 示例：{"id": "human_response", "dependencies": ["check_human"], "required_branch": "human"}\n'
            "- 只有被选中分支上的步骤才会执行；其他步骤将自动跳过\n\n"
            f"{self._PLANNING_GUIDELINES}"
            "难度评估：对于每个步骤，你必须评估其难度等级：\n"
            "- 'easy'：可以快速完成的简单任务（基本搜索、简单计算、直接分析）\n"
            "- 'hard'：需要深入思考、创造性问题解决或大量处理的复杂任务\n\n"
            "语言要求：\n"
            "- 你必须使用与用户目标相同的语言来编写：task_name、步骤名称和步骤描述\n"
            "- 示例：\n"
            "  * 中文目标 → 中文 task_name 和步骤\n"
            "  * 英文目标 → 英文 task_name 和步骤\n"
            "  * 日文目标 → 日文 task_name 和步骤\n\n"
            "始终返回有效的 JSON 格式。"
        )

        logger.debug(f"PLAN GENERATION SYSTEM PROMPT:\n{system_prompt}")

        logger.info(
            f"[generate_plan] Goal: {goal[:100]}, history_count={len(history)}, iteration={iteration}"
        )

        # Build messages list with history
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history as separate messages
        if history:
            messages.extend(history)
            # Log history preview
            first_msg = history[0]
            last_msg = history[-1]
            logger.info(
                f"[generate_plan] History: {len(history)} messages, first={first_msg.get('role')}, last={last_msg.get('role')}"
            )

        # Add current goal as the final user message
        messages.append(
            {
                "role": "user",
                "content": f"目标：{goal}\n迭代次数：{iteration}\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n请创建一个分步执行计划，以 JSON 对象格式返回。",
            }
        )

        # Add skill reminder if available
        if skill_context:
            messages[-1]["content"] += (
                "\n"
                "有一个可用的技能可以帮助完成此任务。"
                "创建计划时请考虑其知识和模板。\n\n"
            )

        # Add plan generation instructions
        messages[-1]["content"] += (
            f"**重要提示**：计划必须包含 'task_name' 字段，提供一个简洁的描述性标题（3-10 个词）。\n\n"
            f"必需字段：\n"
            f"- task_name：任务的简洁标题（必需，3-10 个词，用于任务列表显示，**必须使用与目标相同的语言**）\n"
            f"- steps：执行步骤数组\n\n"
            f"每个步骤必须包含：\n"
            f"- id：唯一标识符（字符串）\n"
            f"- name：步骤名称（字符串）\n"
            f"- description：步骤功能描述（字符串）\n"
            f"- tool_names：此步骤可用的工具列表（字符串数组，可以为空）\n"
            f"- dependencies：此步骤依赖的步骤 ID 列表（字符串数组）\n"
            f"- difficulty：'easy' 或 'hard'（字符串）\n"
            f"- requires_vision：如果步骤需要视觉能力则为 true，否则为 false（布尔值）\n"
            f"- conditional_branches：可选，将分支键映射到下一步骤 ID 的字典（对象）\n"
            f"- required_branch：可选，此步骤需要的分支键（字符串）\n\n"
            f"带条件分支的示例：\n"
            f"{{\n"
            f'  "plan": {{\n'
            f'    "task_name": "客户支持查询处理",\n'
            f'    "goal": "客户支持查询处理",\n'
            f'    "steps": [\n'
            f'      {{"id": "check_intent", "name": "检查意图", "description": "确定是否明确请求人工协助", "tool_names": [], "dependencies": [], "difficulty": "easy", "conditional_branches": {{"human": "human_step", "kb": "kb_step"}}}},\n'
            f'      {{"id": "human_step", "name": "人工响应", "description": "连接到人工客服", "tool_names": [], "dependencies": ["check_intent"], "difficulty": "easy", "required_branch": "human"}},\n'
            f'      {{"id": "kb_step", "name": "知识库搜索", "description": "搜索知识库", "tool_names": ["knowledge_search"], "dependencies": ["check_intent"], "difficulty": "hard", "required_branch": "kb"}}\n'
            f"    ]\n"
            f"  }}\n"
            f"}}\n\n"
            f"不带条件分支的示例：\n"
            f"{{\n"
            f'  "plan": {{\n'
            f'    "task_name": "数据分析与报告",\n'
            f'    "goal": "{goal}",\n'
            f'    "steps": [\n'
            f'      {{"id": "step1", "name": "调研", "description": "收集信息", "tool_names": ["web_search", "zhipu_web_search"], "dependencies": [], "difficulty": "hard"}},\n'
            f'      {{"id": "step2", "name": "数据分析", "description": "分析收集到的信息", "tool_names": ["execute_python_code"], "dependencies": ["step1"], "difficulty": "hard"}},\n'
            f'      {{"id": "step3", "name": "整理结果", "description": "总结并格式化研究结果", "tool_names": [], "dependencies": ["step1", "step2"], "difficulty": "easy"}}\n'
            f"    ]\n"
            f"  }}\n"
            f"}}\n\n"
            f"仅返回 JSON 对象，不要包含其他文本。\n"
            f"**重要语言要求**：以下内容必须使用与目标相同的语言：\n"
            f"- task_name（标题）\n"
            f"- step names（步骤名称）\n"
            f"- step descriptions（步骤描述）\n\n"
            f"例如：\n"
            f"- 如果目标是中文（中文），task_name 必须是中文\n"
            f"- 如果目标是英文，task_name 必须是英文\n"
            f"- 如果目标是日文（日本語），task_name 必须是日文\n"
            f"- 以此类推\n"
        )

        return messages

    def _build_tools_schema(self, tools: List[Tool]) -> List[Dict[str, Any]]:
        """Build tools schema for LLM function calling"""
        tools_schema = []

        for tool in tools:
            try:
                # Get tool arguments schema from the tool's args_type
                args_type = tool.args_type()

                # Convert Pydantic model to JSON schema
                if hasattr(args_type, "model_json_schema"):
                    args_schema = args_type.model_json_schema()
                else:
                    # Fallback for simpler cases
                    args_schema = {"type": "object", "properties": {}, "required": []}

                # Get tool name and description safely
                if tool.metadata:
                    tool_name = tool.metadata.name
                    tool_description = (
                        tool.metadata.description or f"Execute {tool_name}"
                    )
                else:
                    tool_name = getattr(tool, "name", "unknown_tool")
                    tool_description = getattr(
                        tool, "description", f"Execute {tool_name}"
                    )

                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": args_schema,
                    },
                }
                tools_schema.append(tool_schema)

            except Exception as e:
                # Get tool name safely for error message
                if tool.metadata:
                    tool_name = tool.metadata.name
                    tool_description = (
                        tool.metadata.description or f"Execute {tool_name}"
                    )
                else:
                    tool_name = getattr(tool, "name", "unknown_tool")
                    tool_description = getattr(
                        tool, "description", f"Execute {tool_name}"
                    )

                logger.warning(f"Failed to build schema for tool {tool_name}: {e}")
                # Fallback schema
                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                    },
                }
                tools_schema.append(tool_schema)

        return tools_schema

    def _parse_plan_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into plan steps"""
        try:
            # Try to extract JSON from markdown code blocks first
            response = extract_json_from_markdown(response)

            # Try to extract JSON from response
            response = response.strip()

            logger.info(f"response: {response}")
            # Find JSON object in response
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1

            if start_idx < 0 or end_idx <= start_idx:
                raise LLMResponseError(
                    "Could not find valid JSON object in response",
                    response=response,
                    expected_format="JSON object with plan field containing steps array",
                    context={"response_preview": response[:200]},
                )

            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)

            # Handle both formats: {"plan": {"steps": [...]}} and {"steps": [...]}
            plan_data = None

            if isinstance(data, dict):
                if "plan" in data:
                    # Standard format: {"plan": {"steps": [...]}}
                    plan_data = data["plan"]
                elif "steps" in data:
                    # Alternative format: {"steps": [...]}
                    plan_data = data
                    logger.info(
                        "Using alternative JSON format with 'steps' at root level"
                    )

            if (
                plan_data is None
                or not isinstance(plan_data, dict)
                or "steps" not in plan_data
            ):
                raise LLMResponseError(
                    "Response missing valid 'steps' field. Expected format: {'plan': {'steps': [...]}} or {'steps': [...]}",
                    response=response,
                    expected_format="JSON object with steps array (either in 'plan' field or at root)",
                    context={"parsed_data": str(data)[:200]},
                )

            steps = plan_data["steps"]
            if not isinstance(steps, list):
                raise LLMResponseError(
                    "Steps field is not an array",
                    response=response,
                    expected_format="JSON object with plan field containing steps array",
                    context={"steps_type": type(steps).__name__},
                )

            # Validate step structure
            validated_steps = []
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    logger.warning(f"Step {i} is not a dictionary")
                    continue

                # Ensure required fields
                required_fields = ["name", "description", "tool_names"]
                if not all(field in step for field in required_fields):
                    logger.warning(f"Step {i} missing required fields: {step}")
                    continue

                # Set default ID if not provided
                if "id" not in step:
                    step["id"] = f"step_{i + 1}"

                # Set default dependencies if not provided
                if "dependencies" not in step:
                    step["dependencies"] = []

                validated_steps.append(step)

            # Extract task_name if present
            task_name = plan_data.get("task_name")

            # Log if task_name is missing
            if not task_name:
                logger.warning(
                    f"LLM did not generate task_name in plan. Plan data keys: {list(plan_data.keys())}"
                )
            else:
                logger.info(f"LLM generated task_name: {task_name}")

            return {"steps": validated_steps, "task_name": task_name}

        except json.JSONDecodeError as e:
            raise LLMResponseError(
                "Failed to parse JSON response from LLM",
                response=response,
                expected_format="JSON object with plan field containing steps array",
                context={"parse_error": str(e), "response_preview": response[:200]},
                cause=e,
            )
        except Exception as e:
            import traceback

            error_traceback = traceback.format_exc()
            logger.error(
                f"Failed to parse plan response: {str(e)}\ncontent: \n{response}\n{error_traceback}"
            )
            raise LLMResponseError(
                "Failed to parse plan response due to unexpected error",
                response=response,
                expected_format="JSON object with plan field containing steps array",
                context={"error": str(e), "traceback": error_traceback},
                cause=e,
            )

    async def _call_llm_with_retry(
        self, messages: List[Dict[str, str]], **kwargs: Any
    ) -> Any:
        """Call LLM with retry mechanism: JSON mode first, then fallback to normal mode."""
        try:
            # Clean messages before sending to LLM
            cleaned_messages = clean_messages(messages)

            # Use streaming API to collect complete response
            full_content = ""
            usage = {}
            tool_calls = []

            # Check if output_config is provided (for structured outputs with JSON schema)
            # If not, fall back to response_format for simple JSON mode
            llm_params = {}
            if "output_config" in kwargs:
                # Use output_config for structured outputs with JSON schema
                llm_params["output_config"] = kwargs.pop("output_config")
            else:
                # Fall back to simple JSON object mode
                llm_params["response_format"] = {"type": "json_object"}

            async for chunk in self.llm.stream_chat(
                messages=cleaned_messages,
                **llm_params,
                **kwargs,
            ):
                if chunk.is_token():
                    full_content += chunk.delta
                elif chunk.is_tool_call():
                    tool_calls = chunk.tool_calls
                elif chunk.is_usage():
                    usage = chunk.usage
                elif chunk.is_error():
                    raise RuntimeError(f"LLM stream error: {chunk.content}")

            # Record token usage
            if usage:
                logger.info(
                    f"Plan generation LLM usage - prompt_tokens: {usage.get('prompt_tokens', 0)}, "
                    f"completion_tokens: {usage.get('completion_tokens', 0)}, "
                    f"total_tokens: {usage.get('total_tokens', 0)}"
                )

                # Add token usage to tracker
                add_token_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=self.llm.model_name,
                    call_type="plan_generation",
                )

            # Return format (compatible with original chat())
            if tool_calls:
                return {
                    "content": full_content,
                    "tool_calls": tool_calls,
                    "usage": usage,
                }
            return {"content": full_content, "usage": usage}

        except Exception as e:
            logger.warning(f"JSON mode call failed, retrying with normal mode: {e}")

            # Fallback: Use streaming API to retry (without JSON mode)
            try:
                full_content = ""
                usage = {}

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

                # Record token usage for fallback
                if usage:
                    add_token_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=self.llm.model_name,
                        call_type="plan_generation_fallback",
                    )

                return {"content": full_content, "usage": usage}
            except Exception as e2:
                logger.error(f"Normal mode call also failed: {e2}")
                raise

    async def _parse_plan_response_with_retry(
        self,
        content: str,
        messages: List[Dict[str, str]],
        error_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Parse plan response with retry mechanism."""
        # First attempt to parse
        try:
            parsed_data = self._parse_plan_response(content)
            if parsed_data.get("steps"):
                return parsed_data
        except LLMResponseError as e:
            logger.warning(f"First parsing attempt failed: {e}")
            # Continue to retry with error context

        # If parsing failed, retry with non-JSON mode and error information
        logger.warning(
            "JSON parsing failed, retrying LLM call without JSON mode with format clarification and error context"
        )

        # Retry LLM call without JSON mode with clearer format instructions and error context
        cleaned_messages = clean_messages(messages)

        # Build error context for retry
        error_message = ""
        if error_context:
            error_message = "\n\nPREVIOUS ERROR INFORMATION:\n"
            error_message += (
                f"Error Type: {error_context.get('error_type', 'Unknown')}\n"
            )
            error_message += f"Error Message: {error_context.get('error_message', 'Unknown error')}\n"

            # Add specific guidance based on error type
            if error_context.get("error_type") in [
                "DAGStepError",
                "DAGPlanGenerationError",
            ]:
                missing_tools = error_context.get("missing_tools", [])
                if missing_tools:
                    error_message += f"缺失工具：{', '.join(missing_tools)}\n"
                    error_message += "重要：只能使用上方 AVAILABLE TOOLS 列表中提供的工具。\n"
                    error_message += "不要凭空发明，也不要假设存在未列出的工具名。\n"

            error_message += (
                "\n请根据这些错误信息修正计划后再重试。"
            )

        content = (
            f'Please ensure your response is a valid JSON object with the exact format:\n{{\n  "plan": {{\n    "steps": [...]\n  }}\n}}\n\nThe \'steps\' array should contain the execution steps. Do not include any other fields at the top level.{error_message}'
            f"{self._PLANNING_EXAMPLE}"
        )

        # Add format clarification message with error context
        retry_messages = cleaned_messages + [
            {
                "role": "user",
                "content": content,
            }
        ]

        new_response = await self.llm.chat(messages=retry_messages)
        new_content = (
            new_response.get("content", "")
            if isinstance(new_response, dict)
            else str(new_response)
        )

        # Parse the new response
        try:
            parsed_data = self._parse_plan_response(new_content)
            if parsed_data.get("steps"):
                logger.info("Second parsing attempt with error context succeeded")
                return parsed_data
        except LLMResponseError as e:
            logger.warning(f"Second parsing attempt with error context failed: {e}")

        logger.warning("Both parsing attempts failed, returning empty result")
        return {"steps": [], "task_name": None}

    def _validate_steps_tools(self, steps: List[PlanStep], tools: List[Tool]) -> None:
        """
        Validate tool references for a list of steps

        Args:
            steps: List of PlanStep objects to validate
            tools: Available tools

        Raises:
            DAGPlanGenerationError: If any step references non-existent tools
        """
        # Build tool name map for validation
        available_tools = set()
        for tool in tools:
            if hasattr(tool, "metadata") and hasattr(tool.metadata, "name"):
                available_tools.add(tool.metadata.name)
            elif hasattr(tool, "name"):
                available_tools.add(tool.name)

        # Check for missing tools
        missing_tools = []
        for step in steps:
            if step.tool_names:
                for tool_name in step.tool_names:
                    if tool_name not in available_tools:
                        missing_tools.append(f"{step.id}:{tool_name}")
                        logger.warning(
                            f"Step {step.id} references missing tool: {tool_name}"
                        )

        if missing_tools:
            logger.error(f"Step validation failed: missing tools {missing_tools}")
            raise DAGPlanGenerationError(
                "Generated plan references non-existent tools",
                goal="",
                iteration=1,
                llm_response=None,
                context={
                    "missing_tools": missing_tools,
                    "available_tools": list(available_tools),
                },
            )

    def _validate_plan(self, plan: ExecutionPlan, tools: List[Tool]) -> None:
        """
        Validate the generated plan for tool existence

        Args:
            plan: The generated execution plan
            tools: Available tools

        Raises:
            DAGPlanGenerationError: If validation fails
        """
        logger.info(f"Validating plan {plan.id} with {len(plan.steps)} steps")

        # Build tool name map for validation
        available_tools = set()
        for tool in tools:
            if hasattr(tool, "metadata") and hasattr(tool.metadata, "name"):
                available_tools.add(tool.metadata.name)
            elif hasattr(tool, "name"):
                available_tools.add(tool.name)

        logger.debug(f"Available tools for validation: {available_tools}")

        # Check for missing tools
        missing_tools = []
        for step in plan.steps:
            if step.tool_names:
                for tool_name in step.tool_names:
                    if tool_name not in available_tools:
                        missing_tools.append(f"{step.id}:{tool_name}")
                        logger.warning(
                            f"Step {step.id} references missing tool: {tool_name}"
                        )

        if missing_tools:
            logger.error(f"Plan validation failed: missing tools {missing_tools}")
            raise DAGPlanGenerationError(
                "Generated plan references non-existent tools",
                goal=plan.goal,
                iteration=getattr(plan, "iteration", 1),
                llm_response=None,
                context={
                    "missing_tools": missing_tools,
                    "available_tools": list(available_tools),
                },
            )

        # Validate conditional branches
        available_step_ids = {step.id for step in plan.steps}
        invalid_branches = []
        for step in plan.steps:
            if step.conditional_branches:
                for branch_key, target_step_id in step.conditional_branches.items():
                    if target_step_id not in available_step_ids:
                        invalid_branches.append(
                            f"{step.id}.{branch_key} -> {target_step_id}"
                        )
                        logger.warning(
                            f"Step {step.id} branch '{branch_key}' points to non-existent step: {target_step_id}"
                        )

        if invalid_branches:
            logger.error(f"Plan validation failed: invalid branches {invalid_branches}")
            raise DAGPlanGenerationError(
                "Generated plan has conditional branches pointing to non-existent steps",
                goal=plan.goal,
                iteration=getattr(plan, "iteration", 1),
                llm_response=None,
                context={
                    "invalid_branches": invalid_branches,
                    "available_step_ids": list(available_step_ids),
                },
            )

        logger.info(f"Plan {plan.id} validation passed successfully")
