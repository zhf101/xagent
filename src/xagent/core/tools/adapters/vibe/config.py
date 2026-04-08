"""工具配置抽象。

这个模块解决的是“工具工厂需要什么上下文”这一层问题。

在当前项目里，同一套 `ToolFactory` 会被多种入口复用：
- Web 任务执行
- Agent Builder 预览
- 工具列表页
- 纯本地 / 测试 / 脚本调用

如果每个入口都直接把自己手头的参数塞给工具创建函数，
很快就会出现：
- 同一能力在不同入口参数名不一致
- 新增一个运行时约束时，需要改很多调用点
- 某个入口忘了传关键上下文，导致工具行为悄悄分叉

因此这里把“工具创建所需上下文”统一抽象成 `BaseToolConfig`，
再由 Web / standalone 等具体实现负责提供数据。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseToolConfig(ABC):
    """工具配置抽象基类。

    这层边界很关键：工具工厂只依赖“能力契约”，
    不直接依赖 FastAPI request、数据库模型或某个具体页面。
    这样新增运行时入口时，只要实现这份契约，就能复用整套工具创建逻辑。
    """

    @abstractmethod
    def get_workspace_config(self) -> Optional[Dict[str, Any]]:
        """返回 workspace 配置。

        这里描述的是“工具运行时文件边界”，
        不是业务任务本身的全部上下文。
        """
        pass

    @abstractmethod
    def get_vision_model(self) -> Optional[Any]:
        """返回视觉模型实例。"""
        pass

    @abstractmethod
    def get_mcp_server_configs(self) -> List[Dict[str, Any]]:
        """返回当前上下文允许接入的 MCP server 配置。"""
        pass

    @abstractmethod
    def get_file_tools_enabled(self) -> bool:
        """是否启用文件类工具。"""
        pass

    @abstractmethod
    def get_basic_tools_enabled(self) -> bool:
        """是否启用基础工具。"""
        pass

    @abstractmethod
    def get_embedding_model(self) -> Optional[str]:
        """返回 embedding model 标识。"""
        pass

    @abstractmethod
    def get_browser_tools_enabled(self) -> bool:
        """是否启用浏览器自动化工具。"""
        pass

    @abstractmethod
    def get_task_id(self) -> Optional[str]:
        """返回 task_id。

        这个值主要用于：
        - workspace 命名
        - 浏览器会话跟踪
        - 运行时日志归因
        """
        pass

    @abstractmethod
    def get_allowed_collections(self) -> Optional[List[str]]:
        """返回当前上下文允许访问的知识库集合。

        `None` 表示不做集合级收缩，而不是“空集合”。
        """
        pass

    @abstractmethod
    def get_allowed_skills(self) -> Optional[List[str]]:
        """返回允许加载的 skill 名单。"""
        pass

    @abstractmethod
    def get_user_id(self) -> Optional[int]:
        """返回当前用户 ID，用于多租户隔离。"""
        pass

    @abstractmethod
    def is_admin(self) -> bool:
        """返回当前上下文是否具备管理员身份。"""
        pass

    @abstractmethod
    def get_enable_agent_tools(self) -> bool:
        """是否把已发布 Agent 暴露成 Agent tool。"""
        pass

    @abstractmethod
    def get_sandbox(self) -> Optional[Any]:
        """返回 sandbox 实例。

        返回 `None` 表示当前入口不提供沙箱，不代表工具不可用；
        此时工具工厂应按“本地直跑”模式继续创建工具。
        """
        pass

    def get_tool_credential(self, tool_name: str, field_name: str) -> Optional[str]:
        return None

    def get_sql_connections(self) -> Dict[str, str]:
        return {}

    def get_disabled_tool_names(self) -> List[str]:
        """返回被系统策略禁用的工具名列表。

        这里提供默认空实现，原因是工具工厂在很多上下文下都会复用：
        - Web 运行时需要读取数据库中的工具治理策略
        - 纯本地 / 脚本场景通常没有数据库，也不需要这层治理

        因此基类不强制所有实现都关心“工具禁用策略”，但会给运行时统一过滤留出扩展点。
        """
        return []

    def should_enforce_tool_policy(self) -> bool:
        """是否在创建运行时工具时强制执行工具治理策略。"""
        return True

    @abstractmethod
    def get_llm(self) -> Optional[Any]:
        """返回当前运行时绑定的默认 LLM。"""
        pass


class ToolConfig(BaseToolConfig):
    """standalone 场景的轻量配置实现。

    这类配置主要给测试、脚本和不依赖 Web request/db 的本地场景使用。
    它的设计目标不是“功能最全”，而是：
    - 让工具工厂在脱离 Web 时仍可工作
    - 明确哪些能力在 standalone 下天然不可用
    """

    def __init__(self, config_dict: Dict[str, Any]):
        # 这里仍使用宽松 dict 入口，目的是让测试和脚本构造配置足够便宜。
        # 真正复杂、需要数据库感知的逻辑放到 WebToolConfig 里处理。
        workspace_config = config_dict.get("workspace")
        config_dict.get("vision_model")  # Unused in base config
        mcp_server_configs = config_dict.get("mcp_servers", [])
        file_tools_enabled = config_dict.get("file_tools_enabled", True)
        basic_tools_enabled = config_dict.get("basic_tools_enabled", True)
        embedding_model = config_dict.get("embedding_model")
        browser_tools_enabled = config_dict.get("browser_tools_enabled", True)
        task_id = config_dict.get("task_id")
        allowed_collections = config_dict.get("allowed_collections")
        allowed_skills = config_dict.get("allowed_skills")
        allowed_tools = config_dict.get("allowed_tools")
        disabled_tools = config_dict.get("disabled_tools", [])
        enforce_tool_policy = config_dict.get("enforce_tool_policy", True)
        user_id = config_dict.get("user_id")
        is_admin = config_dict.get("is_admin", False)
        tool_credentials = config_dict.get("tool_credentials", {})

        self.workspace_config: Optional[Dict[str, Any]] = workspace_config
        self.vision_model: Optional[Any] = (
            None  # Standalone usage typically doesn't have web context
        )
        self.mcp_server_configs: List[Dict[str, Any]] = mcp_server_configs
        self.file_tools_enabled: bool = bool(file_tools_enabled)
        self.basic_tools_enabled: bool = bool(basic_tools_enabled)
        self.embedding_model: Optional[str] = embedding_model
        self.browser_tools_enabled: bool = bool(browser_tools_enabled)
        self.task_id: Optional[str] = task_id
        self.allowed_collections: Optional[List[str]] = allowed_collections
        self.allowed_skills: Optional[List[str]] = allowed_skills
        self.allowed_tools: Optional[List[str]] = allowed_tools
        self.disabled_tools: List[str] = (
            [tool for tool in disabled_tools if isinstance(tool, str) and tool]
            if isinstance(disabled_tools, list)
            else []
        )
        self.enforce_tool_policy: bool = bool(enforce_tool_policy)
        self.user_id: Optional[int] = user_id
        self.is_admin_value: bool = bool(is_admin)
        self.tool_credentials: Dict[str, Dict[str, str]] = tool_credentials

    def get_workspace_config(self) -> Optional[Dict[str, Any]]:
        return self.workspace_config

    def get_vision_model(self) -> Optional[Any]:
        return self.vision_model

    def get_mcp_server_configs(self) -> List[Dict[str, Any]]:
        return self.mcp_server_configs

    def get_file_tools_enabled(self) -> bool:
        return self.file_tools_enabled

    def get_basic_tools_enabled(self) -> bool:
        return self.basic_tools_enabled

    def get_embedding_model(self) -> Optional[str]:
        return self.embedding_model

    def get_browser_tools_enabled(self) -> bool:
        return self.browser_tools_enabled

    def get_task_id(self) -> Optional[str]:
        return self.task_id

    def get_allowed_collections(self) -> Optional[List[str]]:
        return self.allowed_collections

    def get_allowed_skills(self) -> Optional[List[str]]:
        return self.allowed_skills

    def get_user_id(self) -> Optional[int]:
        return self.user_id

    def is_admin(self) -> bool:
        return self.is_admin_value

    def get_enable_agent_tools(self) -> bool:
        return True

    def get_llm(self) -> Optional[Any]:
        # standalone 配置默认不负责装配真实 LLM；
        # 如需 LLM，由调用方自行在更上层注入。
        return None

    def get_allowed_tools(self) -> Optional[List[str]]:
        return self.allowed_tools

    def get_sandbox(self) -> Optional[Any]:
        return None  # Standalone config doesn't have sandbox

    def get_disabled_tool_names(self) -> List[str]:
        return self.disabled_tools

    def should_enforce_tool_policy(self) -> bool:
        return self.enforce_tool_policy

    def get_tool_credential(self, tool_name: str, field_name: str) -> Optional[str]:
        tool_data = self.tool_credentials.get(tool_name)
        if not isinstance(tool_data, dict):
            return None
        value = tool_data.get(field_name)
        return value if isinstance(value, str) and value else None

    def get_sql_connections(self) -> Dict[str, str]:
        return {}
