from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..memory import MemoryStore
from ..model.chat.basic.base import BaseLLM

# TODO: agent should be separate adaptor for web
from ..tools.adapters.vibe import Tool
from .pattern import AgentPattern

if TYPE_CHECKING:
    from .runner import AgentRunner


class Agent:
    """
    Enhanced Agent that supports nested sub-agents and message-based context.
    """

    def __init__(
        self,
        name: str,
        patterns: List[AgentPattern],
        memory: MemoryStore,
        tools: List[Tool],
        llm: Optional[BaseLLM] = None,
        system_prompt: Optional[str] = None,
    ):
        self.name = name
        self.patterns = patterns
        self.memory = memory  # Keep for backward compatibility
        self.tools = tools
        self.llm = llm
        self._system_prompt = system_prompt  # Store system prompt

        # Enhanced properties for nested agent support
        self._execution_history: Optional[List[Dict[str, str]]] = None
        self._final_result: Optional[Dict[str, Any]] = None
        self._step_id: Optional[str] = None
        self._created_at = datetime.now()

        # Sub-agent management
        self._sub_agents: Dict[str, "Agent"] = {}
        self._parent_agent: Optional["Agent"] = None

    def get_runner(self) -> "AgentRunner":
        """
        返回用于执行该 agent 的 AgentRunner。
        """
        from .runner import AgentRunner

        return AgentRunner(agent=self)

    def add_sub_agent(self, agent: "Agent") -> None:
        """向该 agent 添加一个子 agent。"""
        agent._parent_agent = self
        self._sub_agents[agent.name] = agent

    def get_sub_agent(self, name: str) -> Optional["Agent"]:
        """按名称获取子 agent。"""
        return self._sub_agents.get(name)

    def has_execution_history(self) -> bool:
        """检查该 agent 是否有执行历史。"""
        return self._execution_history is not None

    def get_execution_history(self) -> Optional[List[Dict[str, str]]]:
        """获取完整的执行历史（消息列表）。"""
        return self._execution_history

    def set_execution_history(self, messages: List[Dict[str, str]]) -> None:
        """设置执行历史。"""
        self._execution_history = messages

    def get_final_result(self) -> Optional[Dict[str, Any]]:
        """获取最终执行结果。"""
        return self._final_result

    def set_final_result(self, result: Dict[str, Any]) -> None:
        """Set the final execution result."""
        self._final_result = result

    async def query_execution_details(self, query: str) -> str:
        """Query details about this agent's execution."""
        if not self._execution_history:
            return "No execution history available"

        if not self.llm:
            return "No LLM available for querying"

        # Build query prompt
        history_text = self._format_history_for_query(self._execution_history)

        prompt = [
            {
                "role": "system",
                "content": "你正在回答关于一次历史 agent 执行的问题。"
                "请基于执行历史给出准确、具体的回答。",
            },
            {
                "role": "user",
                "content": f"Agent：{self.name}\n"
                f"执行历史：\n{history_text}\n\n"
                f"最终结果：{self._final_result}\n\n"
                f"问题：{query}",
            },
        ]

        response = await self.llm.chat(messages=prompt)
        return (
            response
            if isinstance(response, str)
            else response.get("content", str(response))
        )

    def _format_history_for_query(self, history: List[Dict[str, str]]) -> str:
        """Format execution history for querying."""
        formatted = []
        for entry in history:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            formatted.append(f"{role.upper()}: {content}")
        return "\n".join(formatted)

    def to_dict(self) -> Dict[str, Any]:
        """将 agent 转换为字典表示。"""
        return {
            "name": self.name,
            "patterns": [pattern.__class__.__name__ for pattern in self.patterns],
            "tools": [tool.metadata.name for tool in self.tools],
            "memory_type": self.memory.__class__.__name__,
            "llm_available": self.llm is not None,
            "sub_agents": list(self._sub_agents.keys()),
            "has_execution_history": self.has_execution_history(),
            "created_at": self._created_at.timestamp(),
            "step_id": self._step_id,
        }
