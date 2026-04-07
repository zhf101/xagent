"""Web ORM 模型的懒加载导出入口。

这个文件的作用有两个：
1. 给外部提供统一 import 入口，避免到处记具体模型文件路径。
2. 在需要时做延迟导入，减少循环依赖。

本次记忆迁移后，`MemoryJob` 也被挂到了这里，
这样数据库初始化和 API 层都能从统一入口拿到它。
"""

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
    "MemoryJob",
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
    "MemoryJob": ".memory_job",
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
    """按名称把模型延迟 import 进来。"""
    module_name = _MODULE_BY_NAME.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


# 这里显式导入一批“必须尽早注册”的 ORM 模型。
# 原因是测试、metadata 初始化、create_all 等流程都依赖这些表已经挂进 Base.metadata。
# 新增的 MemoryJob 也放在这里，避免只写了模型文件却没有真正注册进 SQLAlchemy。
from .agent import Agent  # noqa: F401,E402
from .chat_message import TaskChatMessage  # noqa: F401,E402
from .mcp import MCPServer, UserMCPServer  # noqa: F401,E402
from .memory_job import MemoryJob  # noqa: F401,E402
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
