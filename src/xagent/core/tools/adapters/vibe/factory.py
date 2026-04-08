"""统一工具工厂。

这个模块是“运行时到底能拿到哪些工具”的最终收口点。

它不关心调用入口来自哪里，而只做三件事：
1. 发现所有已注册的工具构造器
2. 根据配置过滤出当前上下文真正允许使用的工具
3. 在需要时补上 workspace / sandbox 等运行时绑定

为什么这里必须作为统一收口点？
- 前端页面隐藏某个工具，并不等于后端运行时真的拿不到它
- Agent Builder、正式任务、预览任务都在复用同一套工具创建逻辑
- 只有在这里做最终过滤，管理员禁用、allowed_tools、沙箱包装等策略才能全局一致
"""

# mypy: ignore-errors

import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from .....config import get_uploads_dir
from .....core.workspace import TaskWorkspace
from .base import Tool
from .config import BaseToolConfig

logger = logging.getLogger(__name__)

__all__ = ["ToolFactory", "ToolRegistry", "register_tool"]


class ToolRegistry:
    """工具构造器注册表。

    每个工具模块通过 `@register_tool` 把自己的 creator 挂进来，
    工厂在运行时统一遍历这些 creator 构造工具实例。

    这套模式的价值在于：
    - 新增工具时，不需要维护一份巨大的手工清单
    - 每个工具模块自己负责注册，边界更清晰
    - 运行时入口只依赖注册结果，不依赖具体工具文件名
    """

    _tool_creators: List[Callable] = []
    _modules_imported = False

    @classmethod
    def register(cls, creator: Callable) -> Callable:
        """
        Register a tool creator function.

        The creator function will be called during create_all_tools()
        with the current config.

        Usage:
            @register_tool
            def create_my_tools(config: BaseToolConfig) -> List[Tool]:
                return [MyTool(...)]
        """
        cls._tool_creators.append(creator)
        return creator

    @classmethod
    def _import_tool_modules(cls):
        """导入工具模块并触发注册副作用。

        这里的 import 看起来像“未使用”，但它们的核心价值就是副作用：
        模块 import 后，`@register_tool` 才会执行，creator 才会进入注册表。
        """
        if cls._modules_imported:
            return

        try:
            # Import tool modules in priority order - these imports trigger @register_tool decorators
            # 这里不要把 import 当成“没用的死代码”。
            # 在本项目里，很多工具模块的注册副作用就发生在 import 阶段。
            from . import (  # noqa: F401 - imports trigger @register_tool decorators
                agent_tool,
                basic_tools,
                browser_tools,
                knowledge_tools,
                mcp_tools,
                pptx_tool,
                skill_tools,
                sql_tool,
                translate_json,
                vision_tool,
                workspace_file_tool,
            )
            # 为什么现在要“这样导入”？
            #   - 以前工具文件就在 src/xagent/core/tools/adapters/vibe/ 包里，所以 factory.py 可以直接：
            #     from . import basic_tools, browser_tools, ...
            #   - 现在把 HTTP/Vanna 相关工具主实现搬到了 src/xagent/gdp/** 它们已经不在 vibe 包下面了
            #   - 所以 factory.py 只能额外显式 import 新位置的模块，才能继续触发注册
            from .....gdp.hrun.adapter import gdp_http_tools  # noqa: F401
            from .....gdp.vanna.adapter import vanna_sql_tools  # noqa: F401

            cls._modules_imported = True
            logger.info("Tool modules imported and registered")
        except Exception as e:
            logger.warning(f"Failed to import tool modules: {e}")

    @classmethod
    async def create_registered_tools(cls, config: BaseToolConfig) -> List[Tool]:
        """执行所有已注册 creator，拿到原始工具集合。"""
        # Import tool modules on first call to trigger decorator registration
        cls._import_tool_modules()

        tools = []
        for creator in cls._tool_creators:
            try:
                created_tools = await creator(config)
                tools.extend(created_tools)
            except Exception as e:
                logger.warning(f"Tool creator {creator.__name__} failed: {e}")

        # Sort tools by category priority
        tools = cls._sort_tools_by_category(tools)
        return tools

    @classmethod
    def _sort_tools_by_category(cls, tools: List[Tool]) -> List[Tool]:
        """Sort tools by category priority.

        Priority order (most important first):
        1. BASIC - Basic tools (search, code execution)
        2. KNOWLEDGE - Knowledge base search
        3. FILE - File operations
        4. VISION - Vision understanding
        5. IMAGE - Image generation
        6. BROWSER - Browser automation
        7. PPT - PPT tools
        8. DATABASE - Database tools (SQL query)
        9. MCP - MCP tools
        10. SKILL - Skill documentation access tools
        11. AGENT - Agent tools (delegation)
        12. OTHER - Other tools
        """
        from .base import ToolCategory

        # Define category priority order
        category_order = {
            ToolCategory.BASIC: 0,
            ToolCategory.KNOWLEDGE: 1,
            ToolCategory.FILE: 2,
            ToolCategory.VISION: 3,
            ToolCategory.IMAGE: 4,
            ToolCategory.BROWSER: 5,
            ToolCategory.PPT: 6,
            ToolCategory.DATABASE: 7,
            ToolCategory.MCP: 8,
            ToolCategory.SKILL: 9,
            ToolCategory.AGENT: 10,
            ToolCategory.OTHER: 11,
        }

        def get_tool_priority(tool: Tool) -> int:
            """Get priority for a tool based on its category."""
            tool_category = tool.metadata.category
            return category_order.get(tool_category, 99)

        return sorted(tools, key=get_tool_priority)


# Decorator for easy import
register_tool = ToolRegistry.register


class ToolFactory:
    """统一工具工厂。

    对上层来说，`create_all_tools()` 是唯一应该依赖的入口。
    它返回的不是“系统里理论存在的全部工具”，而是：
    当前用户、当前任务、当前治理策略、当前运行环境共同作用后的最终工具集。
    """

    @staticmethod
    async def create_all_tools(config: BaseToolConfig) -> List[Tool]:
        """根据配置创建当前运行时真正可用的工具集合。

        过滤顺序有意固定为：
        1. 先发现全部可注册工具
        2. 再做产品级硬裁剪（例如当前分支不开放 image/audio）
        3. 再做调用上下文白名单过滤（`allowed_tools`）
        4. 最后做管理员治理策略过滤（全局禁用）

        这样能保证：
        - 治理策略永远作用在“最终候选集”上
        - 任何入口都不会绕开最后的禁用过滤
        """
        # Auto-discover tools from @register_tool decorators
        tools = await ToolRegistry.create_registered_tools(config)

        # 当前分支只保留文本类能力，显式移除图片生成和音频相关工具。
        from .base import ToolCategory

        disabled_categories = {ToolCategory.IMAGE, ToolCategory.AUDIO}
        tools = [
            tool
            for tool in tools
            if tool.metadata.category not in disabled_categories
        ]

        # Filter tools by allowed_tools if specified
        allowed_tools = config.get_allowed_tools()
        if allowed_tools is not None and len(allowed_tools) > 0:
            tools = [tool for tool in tools if tool.name in allowed_tools]
            logger.info(
                f"Filtered tools to {len(tools)} allowed tools: {[t.name for t in tools]}"
            )
        elif allowed_tools is not None and len(allowed_tools) == 0:
            logger.warning(
                "⚠️ allowed_tools is empty list - this will filter out all tools! If you want to allow all tools, set allowed_tools to None"
            )

        # 运行时最后再执行一层“管理员禁用策略”过滤，确保：
        # 1. 前端页面即便遗漏了按钮禁用，后端也不会把工具交给普通用户
        # 2. 已保存的 Agent / 历史任务在重建执行上下文时，同样拿不到被停用的工具
        # 3. 工具治理不依赖某个具体页面，而是后端统一生效
        disabled_tool_names = set(config.get_disabled_tool_names())
        if config.should_enforce_tool_policy() and disabled_tool_names:
            original_count = len(tools)
            tools = [tool for tool in tools if tool.name not in disabled_tool_names]
            logger.info(
                "Filtered tools by disabled tool policy: %s -> %s",
                original_count,
                len(tools),
            )

        # Wrap sandbox-enabled tools if sandbox is available
        sandbox = config.get_sandbox()
        if sandbox is not None:
            workspace = ToolFactory._create_workspace(config.get_workspace_config())
            if workspace is not None:
                from .sandboxed_tool.sandboxed_tool_wrapper import (
                    create_workspace_in_sandbox,
                )

                await create_workspace_in_sandbox(sandbox, workspace)
            tools = await ToolFactory._wrap_sandbox_tools(tools, sandbox)

        logger.info(f"Created {len(tools)} tools from configuration")
        return tools

    @staticmethod
    async def _wrap_sandbox_tools(tools: List[Tool], sandbox: Any) -> List[Tool]:
        """为需要沙箱隔离的工具补一层 SandboxedToolWrapper。

        这里不是“有 sandbox 就全包一遍”，而是只包装显式声明需要沙箱的工具。
        这样可以避免：
        - 没必要的工具也被强行走远端执行
        - 某个包装失败时把整个工具集都拖垮
        """
        from .sandboxed_tool.sandboxed_tool_config import is_sandbox_enabled
        from .sandboxed_tool.sandboxed_tool_wrapper import create_sandboxed_tool

        wrapped_tools: List[Tool] = []
        for tool in tools:
            if is_sandbox_enabled(tool.name):
                try:
                    wrapped = await create_sandboxed_tool(
                        tool=tool,
                        sandbox=sandbox,
                    )
                    wrapped_tools.append(wrapped)
                    logger.info(f"Wrapped tool '{tool.name}' with sandbox")
                except Exception as e:
                    logger.warning(
                        f"Failed to wrap tool '{tool.name}' with sandbox: {e}, "
                        f"using original tool"
                    )
                    wrapped_tools.append(tool)
            else:
                wrapped_tools.append(tool)
        return wrapped_tools

    # New unified tool creation methods
    @staticmethod
    def _create_workspace(
        workspace_config: Optional[Dict[str, Any]],
    ) -> Optional[TaskWorkspace]:
        """根据配置构造 workspace。

        这里区分真实任务和“仅列举工具”的场景：
        - 真任务：创建实际 workspace，供文件工具和沙箱同步使用
        - 列表页：使用 MockWorkspace，避免光看工具列表就创建一堆磁盘目录
        """
        if not workspace_config:
            return None

        try:
            task_id = workspace_config.get("task_id")

            # Use MockWorkspace for tool listing scenarios
            # This avoids creating unnecessary directories on disk
            if task_id in ("tools_list", "_mock_", None):
                from ....workspace import MockWorkspace

                logger.debug(f"Using MockWorkspace for task_id='{task_id}'")
                return MockWorkspace(
                    id=task_id or "_mock_",
                    base_dir=workspace_config.get("base_dir") or str(get_uploads_dir()),
                )

            # Real task - create actual workspace
            from ....workspace import WorkspaceManager

            workspace_manager = WorkspaceManager()
            workspace = workspace_manager.get_or_create_workspace(
                workspace_config.get("base_dir") or str(get_uploads_dir()),
                task_id or "default",
            )
            return workspace
        except Exception as e:
            logger.warning(f"Failed to create workspace: {e}")
            return None

    @staticmethod
    async def _create_mcp_tools_from_configs(
        mcp_configs: List[Dict[str, Any]],
    ) -> List[Tool]:
        """Create MCP tools from configurations."""
        try:
            from .mcp_adapter import load_mcp_tools_as_agent_tools

            # Convert configs to connection format
            connections = {}
            for config in mcp_configs:
                connection_config = {
                    "transport": config["transport"],
                    **config["config"],
                }

                # Fix args field if it's a string instead of list
                if "args" in connection_config and isinstance(
                    connection_config["args"], str
                ):
                    # Split args string into list, handling quoted arguments
                    import shlex

                    try:
                        connection_config["args"] = shlex.split(
                            connection_config["args"]
                        )
                        logger.info(
                            f"Converted args string to list: {connection_config['args']}"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to parse args string: {e}")
                        # Fallback to simple split
                        connection_config["args"] = connection_config["args"].split()

                connections[config["name"]] = connection_config

            # Load MCP tools
            mcp_tools = await load_mcp_tools_as_agent_tools(connections)  # type: ignore[arg-type]
            return mcp_tools if mcp_tools else []  # type: ignore[return-value]
        except Exception as e:
            logger.warning(f"Failed to create MCP tools: {e}")
            return []

    @classmethod
    async def create_mcp_tools(cls, db: Session, user_id: int | None = None):
        """Create MCP tools from database configuration.

        Args:
            db: Database session
            user_id: User ID for filtering MCP servers

        Returns:
            List of MCP tools
        """
        try:
            from .....web.models.mcp import MCPServer, UserMCPServer
            from ...core.mcp.manager.db import DatabaseMCPServerManager
            from .mcp_adapter import load_mcp_tools_as_agent_tools

            # Load MCP server connections for the specific user
            manager = DatabaseMCPServerManager(db)

            if user_id:

                def filter_by_user(query):
                    return query.join(
                        UserMCPServer, MCPServer.id == UserMCPServer.mcpserver_id
                    ).filter(UserMCPServer.user_id == user_id, UserMCPServer.is_active)

                connections = manager.get_connections(filter_by_user)
            else:
                connections = manager.get_connections()

            if not connections:
                return []

            # Load MCP tools
            mcp_tools = await load_mcp_tools_as_agent_tools(connections)
            return mcp_tools if mcp_tools else []
        except Exception as e:
            logger.warning(f"Failed to create MCP tools from database: {e}")
            return []

    @classmethod
    def _create_mcp_tools(cls, db, user_id: int):
        """Synchronous wrapper for create_mcp_tools.

        Args:
            db: Database session
            user_id: User ID for filtering MCP servers

        Returns:
            List of MCP tools
        """
        import asyncio

        try:
            # Run async method in event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an event loop, we need to create a new one
                import queue
                import threading

                result_queue = queue.Queue()

                def run_async():
                    try:
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        result = new_loop.run_until_complete(
                            cls.create_mcp_tools(db, user_id)
                        )
                        result_queue.put(result)
                    except Exception as e:
                        result_queue.put(e)
                    finally:
                        new_loop.close()

                thread = threading.Thread(target=run_async)
                thread.start()
                thread.join()

                result = result_queue.get()
                if isinstance(result, Exception):
                    raise result
                return result
            else:
                # If no event loop is running, use the current one
                return loop.run_until_complete(cls.create_mcp_tools(db, user_id))
        except Exception as e:
            logger.warning(f"Failed to create MCP tools (sync wrapper): {e}")
            return []
