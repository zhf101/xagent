"""
垂直领域专用 agent 的基类。

本模块为创建特定领域的 agent 提供基础，这些 agent 继承自基础 Agent 类，
同时为 text2sql、code review 等特定垂直领域提供专门的功能。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence

from ..memory import MemoryStore
from ..model.chat.basic.base import BaseLLM
from ..tools.adapters.vibe import Tool
from .agent import Agent
from .context import AgentContext
from .pattern import AgentPattern


class VerticalAgent(Agent, ABC):
    """
    Base class for vertical specialized agents.

    Provides a foundation for domain-specific agents with:
    - Pre-configured domain-specific tools
    - Specialized system prompts
    - Default pattern selection
    - Domain-specific error handling
    """

    def __init__(
        self,
        name: str,
        llm: BaseLLM,
        memory: Optional[MemoryStore] = None,
        tools: Optional[List[Tool]] = None,
        patterns: Optional[List[AgentPattern]] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ):
        """
        Initialize the vertical agent.

        Args:
            name: Agent name
            llm: Language model instance
            memory: Memory store, will use default if not provided
            tools: List of tools, will use domain defaults if not provided
            patterns: List of patterns, will use default pattern if not provided
            system_prompt: System prompt, will use domain default if not provided
            **kwargs: Additional domain-specific configuration
        """
        # Use domain-specific defaults
        if memory is None:
            memory = self._get_default_memory()

        if tools is None:
            tools = list(self._get_domain_tools(**kwargs))

        if patterns is None:
            patterns = list(self._get_domain_patterns(llm, **kwargs))

        if system_prompt is None:
            system_prompt = self._get_domain_prompt(**kwargs)

        # Initialize base agent
        super().__init__(
            name=name,
            patterns=patterns,
            memory=memory,
            tools=tools,
            llm=llm,
        )

        # Store domain configuration and system prompt
        self._domain_config = kwargs
        self._system_prompt = (
            system_prompt  # Store the system prompt for patterns to use
        )

    @abstractmethod
    def _get_domain_tools(self, **kwargs: Any) -> Sequence[Tool]:
        """
        Get the default set of tools for this domain.

        Args:
            **kwargs: Domain-specific configuration

        Returns:
            List of domain-specific tools
        """
        pass

    @abstractmethod
    def _get_domain_patterns(
        self, llm: BaseLLM, **kwargs: Any
    ) -> Sequence[AgentPattern]:
        """
        Get the default patterns for this domain.

        Args:
            llm: Language model instance
            **kwargs: Domain-specific configuration

        Returns:
            List of domain-specific patterns
        """
        pass

    @abstractmethod
    def _get_domain_prompt(self, **kwargs: Any) -> str:
        """
        Get the default system prompt for this domain.

        Args:
            **kwargs: Domain-specific configuration

        Returns:
            Domain-specific system prompt
        """
        pass

    def get_step_trace_data(
        self, step_result: Any, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from step execution result for tracing.

        This method allows vertical agents to provide domain-specific
        structured data that should be sent to the frontend via the trace system.

        Args:
            step_result: The result from step execution
            **kwargs: Additional context about the step

        Returns:
            Structured data dict for trace system, or None if no special data
        """
        return None

    def get_completion_trace_data(
        self, final_result: Any, **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from final execution result for tracing.

        This method allows vertical agents to provide domain-specific
        final result data that should be sent to the frontend via the trace system.

        Args:
            final_result: The final result from agent execution
            **kwargs: Additional context about the execution

        Returns:
            Structured data dict for trace system, or None if no special data
        """
        return None

    def _get_default_memory(self) -> MemoryStore:
        """
        Get the default memory store for this agent.

        Returns:
            Default memory store instance
        """
        from ..memory.in_memory import InMemoryMemoryStore

        return InMemoryMemoryStore()

    def get_domain_info(self) -> Dict[str, Any]:
        """
        Get information about this domain-specific agent.

        Returns:
            Dictionary containing domain information
        """
        return {
            "agent_type": self.__class__.__name__,
            "domain": self._get_domain_name(),
            "tools": [
                tool.metadata.name for tool in self.tools if hasattr(tool, "metadata")
            ],
            "patterns": [pattern.__class__.__name__ for pattern in self.patterns],
            "config": self._domain_config,
        }

    @abstractmethod
    def _get_domain_name(self) -> str:
        """
        Get the domain name for this agent.

        Returns:
            Domain name string
        """
        pass

    async def execute(
        self,
        task: str,
        pattern_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute a task using this domain-specific agent.

        Args:
            task: The task to execute
            pattern_name: Specific pattern to use, will use default if not provided
            **kwargs: Additional execution parameters

        Returns:
            Execution result
        """
        # Select pattern
        if pattern_name:
            pattern = next(
                (p for p in self.patterns if p.__class__.__name__ == pattern_name), None
            )
            if not pattern:
                raise ValueError(
                    f"Pattern '{pattern_name}' not found in available patterns"
                )
        else:
            # Use first pattern as default
            pattern = self.patterns[0] if self.patterns else None

        if not pattern:
            raise ValueError("No patterns available for execution")

        # Execute with domain-specific context
        context_data = self._build_execution_context(task, **kwargs)
        # Convert dict to AgentContext if needed
        agent_context = (
            AgentContext(**context_data)
            if isinstance(context_data, dict)
            else context_data
        )

        try:
            result = await pattern.run(
                task=task,
                memory=self.memory,
                tools=self.tools,
                context=agent_context,
            )

            # Post-process result with domain-specific logic
            return self._post_process_result(result, task, **kwargs)

        except Exception as e:
            # Handle domain-specific errors
            return self._handle_domain_error(e, task, **kwargs)

    def _build_execution_context(self, task: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Build execution context with domain-specific information.

        Args:
            task: The task being executed
            **kwargs: Additional parameters

        Returns:
            Execution context dictionary
        """
        # Build state dict first
        state = {
            "agent_type": self.__class__.__name__,
            "domain": self._get_domain_name(),
            "task": task,
        }

        # Add system prompt to state if available (for ReAct pattern to use)
        if hasattr(self, "_system_prompt") and self._system_prompt:
            state["system_prompt"] = self._system_prompt

        # Add domain-specific context to state
        domain_context = self._get_domain_context(task, **kwargs)
        state.update(domain_context)

        # Add any additional kwargs to state
        state.update(kwargs)

        # Return context with state properly nested
        context = {"state": state}

        return context

    def _get_domain_context(self, task: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Get domain-specific context for the task.

        Args:
            task: The task being executed
            **kwargs: Additional parameters

        Returns:
            Domain-specific context
        """
        return {}

    def _post_process_result(
        self, result: Dict[str, Any], task: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Post-process the execution result with domain-specific logic.

        Args:
            result: The raw execution result
            task: The original task
            **kwargs: Additional parameters

        Returns:
            Post-processed result
        """
        # Add domain information to result
        if "metadata" not in result:
            result["metadata"] = {}

        result["metadata"]["agent_type"] = self.__class__.__name__
        result["metadata"]["domain"] = self._get_domain_name()

        return result

    def _handle_domain_error(
        self, error: Exception, task: str, **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Handle domain-specific errors.

        Args:
            error: The exception that occurred
            task: The original task
            **kwargs: Additional parameters

        Returns:
            Error result with domain context
        """
        from .exceptions import PatternExecutionError

        if isinstance(error, PatternExecutionError):
            # Re-raise pattern execution errors
            raise error

        # Wrap other errors with domain context
        domain_error = PatternExecutionError(
            pattern_name=self.__class__.__name__,
            message=f"Domain-specific error in {self._get_domain_name()}: {str(error)}",
            context={
                "domain": self._get_domain_name(),
                "task": task[:100],
                "error_type": type(error).__name__,
            },
            cause=error,
        )

        raise domain_error
