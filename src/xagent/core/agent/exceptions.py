"""
Agent execution exceptions hierarchy.

This module defines specific exceptions for different failure scenarios
in agent execution, replacing generic string error handling.
"""

from typing import Any, Dict, List, Optional


class AgentException(Exception):
    """所有 agent 相关错误的基础异常类。"""

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.context = context or {}
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        """将异常转换为字典以便序列化。"""
        return {
            "type": self.__class__.__name__,
            "message": str(self),
            "context": self.context,
            "cause": str(self.cause) if self.cause else None,
        }


class AgentConfigurationError(AgentException):
    """当 agent 配置错误时抛出。"""

    pass


class LLMError(AgentException):
    """LLM 相关错误的基础类。"""

    pass


class LLMNotAvailableError(LLMError):
    """当需要 LLM 但未配置时抛出。"""

    pass


class LLMResponseError(LLMError):
    """当 LLM 返回无效或无法解析的响应时抛出。"""

    def __init__(
        self,
        message: str,
        response: Any = None,
        expected_format: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message, context=context, cause=cause)
        self.response = response
        self.expected_format = expected_format
        if response is not None:
            self.context["response"] = str(response)[:500]  # Truncate for safety
        if expected_format:
            self.context["expected_format"] = expected_format


class ToolError(AgentException):
    """工具执行错误的基础类。"""

    pass


class ToolNotFoundError(ToolError):
    """当所需的工具不可用时抛出。"""

    def __init__(
        self, tool_name: str, available_tools: Optional[List[str]] = None, **kwargs: Any
    ) -> None:
        message = f"Tool '{tool_name}' not found"
        if available_tools:
            message += f"。可用工具：{', '.join(available_tools)}"
        super().__init__(message, **kwargs)
        self.tool_name = tool_name
        self.available_tools = available_tools or []
        self.context.update(
            {"tool_name": tool_name, "available_tools": self.available_tools}
        )


class ToolExecutionError(ToolError):
    """当工具执行失败时抛出。"""

    def __init__(
        self,
        tool_name: str,
        message: str,
        tool_args: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(f"Tool '{tool_name}' execution failed: {message}", **kwargs)
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.context.update({"tool_name": tool_name, "tool_args": self.tool_args})


class PatternError(AgentException):
    """模式执行错误的基础类。"""

    pass


class PatternExecutionError(PatternError):
    """当模式执行失败时抛出。"""

    def __init__(
        self,
        pattern_name: str,
        message: str,
        iteration: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.raw_message = message
        super().__init__(f"Pattern '{pattern_name}' failed: {message}", **kwargs)
        self.pattern_name = pattern_name
        self.iteration = iteration
        self.context.update({"pattern_name": pattern_name, "iteration": iteration})


class MaxIterationsError(PatternError):
    """当模式达到最大迭代次数仍未完成时抛出。"""

    def __init__(
        self,
        pattern_name: str,
        max_iterations: int,
        final_state: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        message = (
            f"Pattern '{pattern_name}' reached maximum iterations ({max_iterations})"
        )
        if final_state:
            message += f". Final state: {final_state}"

        # Add execution summary to message if available
        if "execution_summary" in kwargs.get("context", {}):
            execution_summary = kwargs["context"]["execution_summary"]
            message += "\n\nExecution summary:\n" + "\n".join(execution_summary)

        # Add iteration count if available
        if "total_iterations" in kwargs.get("context", {}):
            total_iterations = kwargs["context"]["total_iterations"]
            message += f"\n\nTotal iterations completed: {total_iterations}"

        super().__init__(message, **kwargs)
        self.pattern_name = pattern_name
        self.max_iterations = max_iterations
        self.final_state = final_state
        self.context.update(
            {
                "pattern_name": pattern_name,
                "max_iterations": max_iterations,
                "final_state": final_state,
            }
        )


class DAGError(AgentException):
    """DAG 执行错误的基础类。"""

    pass


class DAGPlanGenerationError(DAGError):
    """当 DAG 计划生成失败时抛出。"""

    def __init__(
        self,
        message: str,
        iteration: Optional[int] = None,
        llm_response: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        # Extract context and cause from kwargs, filter out other parameters
        context = kwargs.pop("context", None)
        cause = kwargs.pop("cause", None)

        # Any remaining kwargs can be added to context
        if kwargs:
            context = context or {}
            context.update(kwargs)

        super().__init__(
            f"DAG plan generation failed: {message}", context=context, cause=cause
        )
        self.iteration = iteration
        self.llm_response = llm_response
        if iteration is not None:
            self.context["iteration"] = iteration
        if llm_response:
            self.context["llm_response"] = llm_response[:500]  # Truncate


class DAGStepError(DAGError):
    """当 DAG 步骤失败时抛出。"""

    def __init__(
        self,
        step_id: str,
        step_name: str,
        message: str,
        dependencies: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        # Build a more detailed error message that includes original exception info
        detailed_message = f"DAG step '{step_id}' ({step_name}) failed: {message}"

        # If there's a cause exception, include its type in the message
        if "cause" in kwargs and kwargs["cause"]:
            cause = kwargs["cause"]
            detailed_message += (
                f" (caused by: {cause.__class__.__name__}: {str(cause)})"
            )

        super().__init__(detailed_message, **kwargs)
        self.step_id = step_id
        self.step_name = step_name
        self.dependencies = dependencies or []
        self.context.update(
            {
                "step_id": step_id,
                "step_name": step_name,
                "dependencies": self.dependencies,
            }
        )

        # Add original exception details to context if available
        if "cause" in kwargs and kwargs["cause"]:
            cause = kwargs["cause"]
            self.context.update(
                {
                    "original_exception_type": cause.__class__.__name__,
                    "original_exception_message": str(cause),
                }
            )


class DAGDependencyError(DAGError):
    """当 DAG 依赖验证失败时抛出。"""

    def __init__(
        self, step_id: str, invalid_dependencies: List[str], **kwargs: Any
    ) -> None:
        message = f"Step '{step_id}' has invalid dependencies: {', '.join(invalid_dependencies)}"
        super().__init__(message, **kwargs)
        self.step_id = step_id
        self.invalid_dependencies = invalid_dependencies
        self.context.update(
            {"step_id": step_id, "invalid_dependencies": invalid_dependencies}
        )


class DAGDeadlockError(DAGError):
    """当 DAG 执行因依赖死锁而卡住时抛出。"""

    def __init__(
        self,
        pending_steps: List[str],
        blocked_dependencies: Dict[str, List[str]],
        **kwargs: Any,
    ) -> None:
        message = f"DAG execution deadlock detected. Pending steps: {', '.join(pending_steps)}"
        if blocked_dependencies:
            blocked_deps_str = "; ".join(
                f"{step}: {', '.join(deps)}"
                for step, deps in blocked_dependencies.items()
            )
            message += f". Blocked dependencies: {blocked_deps_str}"

        super().__init__(message, **kwargs)
        self.pending_steps = pending_steps
        self.blocked_dependencies = blocked_dependencies
        self.context.update(
            {
                "pending_steps": pending_steps,
                "blocked_dependencies": blocked_dependencies,
            }
        )


class DAGExecutionError(DAGError):
    """当 DAG 执行因步骤失败而失败时抛出。"""

    def __init__(
        self,
        message: str,
        failed_steps: List[Any],
        completed_steps: int,
        total_steps: int,
        primary_error: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.failed_steps = failed_steps
        self.completed_steps = completed_steps
        self.total_steps = total_steps
        self.primary_error = primary_error
        self.context.update(
            {
                "failed_steps_count": len(failed_steps),
                "completed_steps": completed_steps,
                "total_steps": total_steps,
                "primary_error": primary_error,
                "failed_step_names": [f"{s.id} ({s.name})" for s in failed_steps],
            }
        )


class ReActError(PatternError):
    """ReAct 模式错误的基础类。"""

    pass


class ReActParsingError(ReActError):
    """当 ReAct 无法解析 LLM 响应时抛出。"""

    def __init__(
        self,
        message: str,
        response: Any = None,
        iteration: Optional[int] = None,
        expected_format: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(
            f"ReAct parsing failed: {message}", context=context, cause=cause
        )
        self.response = response
        self.iteration = iteration
        self.expected_format = expected_format
        if response is not None:
            self.context["response"] = str(response)[:500]
        if iteration is not None:
            self.context["iteration"] = iteration
        if expected_format:
            self.context["expected_format"] = expected_format


class ContextError(AgentException):
    """上下文管理错误的基础类。"""

    pass


class ContextCompactionError(ContextError):
    """当上下文压缩失败时抛出。"""

    def __init__(
        self,
        message: str,
        original_size: Optional[int] = None,
        target_step: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(f"Context compaction failed: {message}", **kwargs)
        self.original_size = original_size
        self.target_step = target_step
        self.context.update(
            {"original_size": original_size, "target_step": target_step}
        )


class AgentToolError(ToolError):
    """当 AgentTool（嵌套 agent）执行失败时抛出。"""

    def __init__(
        self,
        agent_name: str,
        message: str,
        sub_agent_error: Optional[Exception] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(f"Sub-agent '{agent_name}' failed: {message}", **kwargs)
        self.agent_name = agent_name
        self.sub_agent_error = sub_agent_error
        self.context.update(
            {
                "agent_name": agent_name,
                "sub_agent_error": str(sub_agent_error) if sub_agent_error else None,
            }
        )


def create_execution_error(
    error_type: str,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    cause: Optional[Exception] = None,
) -> AgentException:
    """
    Factory function to create appropriate exception types.

    Useful for converting from legacy string-based error handling.
    """
    error_map = {
        "pattern_execution_error": PatternExecutionError,
        "max_iterations": MaxIterationsError,
        "dag_plan_generation": DAGPlanGenerationError,
        "dag_step_error": DAGStepError,
        "dag_dependency_error": DAGDependencyError,
        "react_parsing_error": ReActParsingError,
        "context_compaction_error": ContextCompactionError,
        "agent_tool_error": AgentToolError,
    }

    # Use error_map to get appropriate exception type
    exception_cls = error_map.get(error_type, AgentException)
    return exception_cls(message, context=context, cause=cause)  # type: ignore
