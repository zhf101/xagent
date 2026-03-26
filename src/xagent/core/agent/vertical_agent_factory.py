"""
Vertical Agent Factory for creating domain-specific agents.

This module provides a factory for creating vertical agents based on
configuration, eliminating the need to modify AgentService when adding
new vertical agents.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type, Union

from ..memory import MemoryStore
from ..memory.in_memory import InMemoryMemoryStore
from ..model.chat.basic.base import BaseLLM
from ..tools.adapters.vibe import Tool
from .agent import Agent
from .vertical_agent import VerticalAgent

logger = logging.getLogger(__name__)


class VerticalAgentFactory:
    """Factory for creating vertical agents based on configuration."""

    _vertical_agents: Dict[str, Type[VerticalAgent]] = {}
    _initialized = False

    @classmethod
    def register_vertical_agent(
        cls, name: str, agent_class: Type[VerticalAgent]
    ) -> None:
        """
        Register a vertical agent class.

        Args:
            name: Name of the vertical agent (e.g., "code_review")
            agent_class: Class that inherits from VerticalAgent
        """
        cls._vertical_agents[name.lower()] = agent_class
        logger.info(f"Registered vertical agent: {name} -> {agent_class.__name__}")

    @classmethod
    def get_registered_agents(cls) -> List[str]:
        """Get list of registered vertical agent names."""
        return list(cls._vertical_agents.keys())

    @classmethod
    def create_agent(
        cls,
        agent_type: str,
        name: str,
        llm: BaseLLM,
        memory: Optional[MemoryStore] = None,
        tools: Optional[List[Tool]] = None,
        **kwargs: Any,
    ) -> Union[Agent, VerticalAgent]:
        """
        Create an agent based on the specified type.

        Args:
            agent_type: Type of agent to create (e.g., "standard", "code_review")
            name: Name for the agent
            llm: Language model for the agent
            memory: Memory store for the agent
            tools: List of tools for the agent
            **kwargs: Additional configuration parameters

        Returns:
            Agent instance (either standard Agent or VerticalAgent)

        Raises:
            ValueError: If agent_type is not supported
        """
        # Ensure vertical agents are registered
        cls._ensure_initialized()

        agent_type_lower = agent_type.lower()

        # Check if this is a registered vertical agent
        if agent_type_lower in cls._vertical_agents:
            agent_class = cls._vertical_agents[agent_type_lower]
            logger.info(
                f"Creating vertical agent: {agent_type} -> {agent_class.__name__}"
            )

            # Create vertical agent - vertical agents create their own tools
            try:
                # Don't pass tools/patterns/system_prompt parameters to vertical agents as they create their own
                excluded_params = {"tools", "patterns", "system_prompt"}
                vertical_kwargs = {
                    k: v for k, v in kwargs.items() if k not in excluded_params
                }
                return agent_class(name=name, llm=llm, memory=memory, **vertical_kwargs)
            except Exception as e:
                logger.error(f"Failed to create vertical agent {agent_type}: {e}")
                raise ValueError(
                    f"Failed to create vertical agent {agent_type}: {str(e)}"
                )

        # If not a vertical agent, create standard agent
        if agent_type_lower in ("standard", "agent", "default"):
            logger.info(f"Creating standard agent: {name}")
            # For standard agents, pass patterns if provided, otherwise use empty list
            patterns = kwargs.get("patterns", [])

            # Filter out agent-specific kwargs that Agent doesn't accept
            agent_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k not in ["patterns", "workspace", "tracer", "task_id"]
            }

            return Agent(
                name=name,
                patterns=patterns,
                memory=memory or InMemoryMemoryStore(),
                tools=tools or [],
                llm=llm,
                **agent_kwargs,
            )

        # Unknown agent type
        available_types = ["standard"] + list(cls._vertical_agents.keys())
        raise ValueError(
            f"Unknown agent type: {agent_type}. Available types: {available_types}"
        )

    @classmethod
    def _ensure_initialized(cls) -> None:
        """Ensure vertical agents are registered."""
        if not cls._initialized:
            cls._register_default_agents()
            cls._initialized = True

    @classmethod
    def _register_default_agents(cls) -> None:
        """Register default vertical agents."""
        from ...datamakepool.agents.orchestrator import DatamakepoolOrchestratorAgent

        cls.register_vertical_agent(
            "datamakepool_orchestrator", DatamakepoolOrchestratorAgent
        )


def create_agent(
    agent_type: str,
    name: str,
    llm: BaseLLM,
    memory: Optional[MemoryStore] = None,
    tools: Optional[List[Tool]] = None,
    **kwargs: Any,
) -> Union[Agent, VerticalAgent]:
    """
    Convenience function to create an agent.

    This is a thin wrapper around VerticalAgentFactory.create_agent
    for easier use and backward compatibility.
    """
    return VerticalAgentFactory.create_agent(
        agent_type=agent_type, name=name, llm=llm, memory=memory, tools=tools, **kwargs
    )
