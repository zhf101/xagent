"""Lazy exports for web ORM models."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "Base",
    "get_engine",
    "get_db",
    "get_session_local",
    "User",
    "UserModel",
    "UserDefaultModel",
    "UserOAuth",
    "UserChannel",
    "Model",
    "MCPServer",
    "UserMCPServer",
    "Task",
    "DAGExecution",
    "TemplateStats",
    "ToolConfig",
    "ToolUsage",
    "SystemSetting",
    "Agent",
    "TaskChatMessage",
    "UploadedFile",
    "SandboxInfo",
]

_MODULE_BY_NAME = {
    "Base": ".database",
    "get_engine": ".database",
    "get_db": ".database",
    "get_session_local": ".database",
    "User": ".user",
    "UserModel": ".user",
    "UserDefaultModel": ".user",
    "UserOAuth": ".user_oauth",
    "UserChannel": ".user_channel",
    "Model": ".model",
    "MCPServer": ".mcp",
    "UserMCPServer": ".mcp",
    "Task": ".task",
    "DAGExecution": ".task",
    "TemplateStats": ".template_stats",
    "ToolConfig": ".tool_config",
    "ToolUsage": ".tool_config",
    "SystemSetting": ".system_setting",
    "Agent": ".agent",
    "TaskChatMessage": ".chat_message",
    "UploadedFile": ".uploaded_file",
    "SandboxInfo": ".sandbox",
}


def __getattr__(name: str):
    module_name = _MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


# Eagerly register legacy ORM tables that are needed by tests and metadata setup,
# while keeping GDP-domain wrappers lazy to avoid circular imports.
from .agent import Agent  # noqa: F401,E402
from .chat_message import TaskChatMessage  # noqa: F401,E402
from .mcp import MCPServer, UserMCPServer  # noqa: F401,E402
from .model import Model  # noqa: F401,E402
from .sandbox import SandboxInfo  # noqa: F401,E402
from .system_setting import SystemSetting  # noqa: F401,E402
from .task import DAGExecution, Task  # noqa: F401,E402
from .template_stats import TemplateStats  # noqa: F401,E402
from .tool_config import ToolConfig, ToolUsage  # noqa: F401,E402
from .uploaded_file import UploadedFile  # noqa: F401,E402
from .user import User, UserDefaultModel, UserModel  # noqa: F401,E402
from .user_channel import UserChannel  # noqa: F401,E402
from .user_oauth import UserOAuth  # noqa: F401,E402
from ...gdp.vanna.model.text2sql import Text2SQLDatabase  # noqa: F401,E402
