"""Web 运行时工具配置。

这个模块是 Web 层和工具工厂之间的“翻译层”：
- Web 层掌握 request、数据库、当前用户、任务上下文
- ToolFactory 只认识 `BaseToolConfig` 这套抽象契约

`WebToolConfig` 的职责不是创建工具本身，而是把 Web 运行时里的业务事实
规整成工具工厂可消费的配置视图，例如：
- 当前用户是谁、是不是管理员
- 当前任务允许哪些知识库 / skills / tools
- 当前系统是否有全局禁用的工具策略
- 当前用户的 SQL 连接、工具密钥、MCP 配置是什么
"""

import logging
from typing import Any, Dict, List, Optional

from ...config import get_uploads_dir
from ...core.tools.adapters.vibe.config import BaseToolConfig
from ..services.tool_credentials import get_sql_connection_map, resolve_tool_credential


class WebToolConfig(BaseToolConfig):
    """Web 场景下的工具配置实现。

    这里优先保证“运行时语义统一”，而不是追求懒加载极致简单。
    原因是同一个用户在不同入口看到的工具集合、权限边界、配置依赖必须一致，
    否则很容易出现：
    - 工具页看得到，任务执行拿不到
    - 管理员刚禁用，历史任务还能继续用
    - 预览和正式运行因为上下文读取不同而行为分叉
    """

    @staticmethod
    def _coerce_user_id(value: Any) -> Optional[int]:
        return value if isinstance(value, int) else None

    def __init__(
        self,
        db: Any,
        request: Any,
        user_id: Optional[int] = None,
        is_admin: bool = False,
        workspace_config: Optional[Dict[str, Any]] = None,
        vision_model: Optional[Any] = None,
        llm: Optional[Any] = None,
        include_mcp_tools: bool = True,
        task_id: Optional[str] = None,
        workspace_base_dir: Optional[str] = None,
        browser_tools_enabled: bool = True,
        allowed_collections: Optional[List[str]] = None,
        allowed_skills: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        enforce_tool_policy: bool = True,
    ):
        self.db = db
        self.request = request
        self._user_id = (
            user_id if user_id is not None else self._get_user_id_from_request(request)
        )
        self._is_admin_value = is_admin or self._get_is_admin_from_request(request)
        # Initialize workspace_config with base_dir and task_id if provided
        if workspace_config is None:
            workspace_config = {}
        if task_id:
            workspace_config["task_id"] = task_id
        # Use uploads dir if workspace_base_dir not explicitly provided
        if workspace_base_dir is None:
            workspace_base_dir = str(get_uploads_dir())
        # Ensure base_dir is in workspace_config (required by ToolFactory._create_workspace)
        if "base_dir" not in workspace_config:
            workspace_config["base_dir"] = workspace_base_dir
        self._workspace_config = workspace_config
        self._explicit_vision_model = vision_model
        self._explicit_llm = llm
        self._include_mcp_tools = include_mcp_tools
        self._task_id = task_id
        self._browser_tools_enabled = browser_tools_enabled
        self._allowed_collections = allowed_collections
        self._allowed_skills = allowed_skills
        self._allowed_tools = allowed_tools
        # 列表页需要展示“已禁用工具”，但真正运行时必须挡住它们，所以这里用显式开关区分展示链路和执行链路。
        self._enforce_tool_policy = enforce_tool_policy
        self._excluded_agent_id: Optional[int] = None

        # Sandbox instance - only store reference, lifecycle managed by upper layer
        self._sandbox: Optional[Any] = None

        # Cache for loaded configurations
        self._cached_vision_config: Optional[Any] = None
        self._cached_mcp_configs: Optional[List[Dict[str, Any]]] = None
        self._cached_embedding_model: Optional[str] = None
        self._cached_disabled_tool_names: Optional[List[str]] = None

    def _get_user_id_from_request(self, request: Any) -> int:
        """从 request 里尽量稳定地提取用户 ID。

        这里兼容多种入口：
        - 标准 FastAPI HTTP 请求
        - 手工构造的 preview/mock request
        - 已提前挂好 `request.user` 的上下文

        兜底返回 `1` 只是为了兼容历史代码路径，
        不代表生产环境应该长期依赖这个 fallback。
        """
        try:
            from ..auth_dependencies import get_user_from_websocket_token

            # Check if this is a FastAPI request with proper authentication
            if hasattr(request, "headers") and hasattr(request, "query_params"):
                # Try to extract user from Authorization header
                auth_header = request.headers.get("authorization")
                if auth_header:
                    user = get_user_from_websocket_token(auth_header, self.db)
                    if user is not None:
                        user_id = self._coerce_user_id(getattr(user, "id", None))
                        if user_id is not None:
                            return user_id

            # If request has a user attribute directly, use it
            if hasattr(request, "user") and request.user:
                user_id = self._coerce_user_id(getattr(request.user, "id", None))
                if user_id is not None:
                    return user_id

            # If no authentication, this should raise an exception
            raise ValueError("Authentication required")

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to get user ID from request: {e}")
            # Fallback to default user ID for backward compatibility
            # In production, this should raise an exception instead
            return 1

    def _get_is_admin_from_request(self, request: Any) -> bool:
        """从 request 中提取管理员标记。"""
        try:
            # If request has a user attribute directly, check is_admin
            if hasattr(request, "user") and request.user:
                return bool(request.user.is_admin)

            return False

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to get is_admin from request: {e}")
            return False

    def get_workspace_config(self) -> Optional[Dict[str, Any]]:
        """返回 workspace 配置。"""
        return self._workspace_config

    def get_file_tools_enabled(self) -> bool:
        """Whether to include file tools."""
        return True

    def get_basic_tools_enabled(self) -> bool:
        """Whether to include basic tools."""
        return True

    def get_vision_model(self) -> Optional[Any]:
        """返回视觉模型，且显式传入优先于数据库默认值。

        这样任务级/预览级显式指定模型时，不会被用户默认配置悄悄覆盖。
        """
        if hasattr(self, "_explicit_vision_model") and self._explicit_vision_model:
            return self._explicit_vision_model

        if self._cached_vision_config is None:
            self._cached_vision_config = self._load_vision_model()
        return self._cached_vision_config

    def get_mcp_server_configs(self) -> List[Dict[str, Any]]:
        """返回当前用户可见且已启用的 MCP server 配置。"""
        if self._cached_mcp_configs is None:
            self._cached_mcp_configs = self._load_mcp_server_configs()
        return self._cached_mcp_configs

    def get_embedding_model(self) -> Optional[str]:
        """返回当前用户的默认 embedding model 标识。"""
        if self._cached_embedding_model is None:
            self._cached_embedding_model = self._load_embedding_model()
        return self._cached_embedding_model

    def get_browser_tools_enabled(self) -> bool:
        """Whether to include browser automation tools."""
        return self._browser_tools_enabled

    def get_task_id(self) -> Optional[str]:
        """返回当前 task_id。"""
        return self._task_id

    def get_allowed_collections(self) -> Optional[List[str]]:
        """返回当前上下文允许访问的知识库名单。"""
        return self._allowed_collections

    def get_allowed_skills(self) -> Optional[List[str]]:
        """返回当前上下文允许访问的 skill 名单。"""
        return self._allowed_skills

    def get_allowed_tools(self) -> Optional[List[str]]:
        """返回白名单模式下允许创建的工具名。"""
        return self._allowed_tools

    def get_disabled_tool_names(self) -> List[str]:
        """返回被管理员全局禁用的工具名。

        这个列表只用于“真正要执行工具”的运行时链路。
        对于工具管理页，我们会显式关闭策略执行，让前端还能看见这些工具并继续管理它们。
        """
        if not self._enforce_tool_policy:
            return []

        if self._cached_disabled_tool_names is None:
            self._cached_disabled_tool_names = self._load_disabled_tool_names()
        return list(self._cached_disabled_tool_names)

    def should_enforce_tool_policy(self) -> bool:
        """当前配置是否要求工具工厂执行数据库里的启停策略。"""
        return self._enforce_tool_policy

    def get_excluded_agent_id(self) -> Optional[int]:
        """返回需要从 Agent tools 中排除的 Agent ID。

        这个字段主要用于避免“某个已发布 Agent 把自己再次作为工具调用”。
        """
        return getattr(self, "_excluded_agent_id", None)

    def get_user_id(self) -> Optional[int]:
        """返回当前用户 ID，用于多租户隔离。"""
        return self._user_id

    def get_db(self) -> Any:
        """返回数据库 session。"""
        return self.db

    def is_admin(self) -> bool:
        """返回当前用户是否为管理员。"""
        return self._is_admin_value

    def get_enable_agent_tools(self) -> bool:
        """当前实现总是允许已发布 Agent 参与工具发现。"""
        return True

    def get_sandbox(self) -> Optional[Any]:
        """返回当前任务绑定的 sandbox 实例。"""
        return self._sandbox

    def get_tool_credential(self, tool_name: str, field_name: str) -> Optional[str]:
        """读取工具密钥。

        密钥解析统一走 `tool_credentials` service，
        这样 WebToolConfig 不需要关心“管理员全局密钥”和“用户私有配置”如何合并。
        """
        return resolve_tool_credential(self.db, tool_name, field_name)

    def get_sql_connections(self) -> Dict[str, str]:
        """返回当前用户可用的数据源连接映射。"""
        return get_sql_connection_map(self.db, self._user_id)

    def set_sandbox(self, sandbox: Any) -> None:
        """挂入 sandbox 实例。

        sandbox 生命周期由更上层负责，这里只保存引用，不负责创建或销毁。
        """
        self._sandbox = sandbox

    def _load_embedding_model(self) -> Optional[str]:
        """通过 model service 读取默认 embedding model。"""
        from ...web.services.model_service import get_default_embedding_model

        return get_default_embedding_model(self._user_id)

    def _load_disabled_tool_names(self) -> List[str]:
        """从数据库读取被管理员显式禁用的工具名列表。

        这里故意只读取 `enabled = false` 的记录，不去推断“没配置就是禁用”。
        原因是当前产品语义非常明确：
        - 管理员在工具治理页主动点了禁用，才应该拦截运行时
        - 没有治理记录的工具，仍按默认可用处理
        """
        logger = logging.getLogger(__name__)
        if self.db is None:
            return []

        try:
            from ..models.tool_config import ToolConfig as ToolConfigModel

            rows = (
                self.db.query(ToolConfigModel.tool_name)
                .filter(ToolConfigModel.enabled.is_(False))
                .all()
            )
        except Exception as exc:
            logger.warning("Failed to load disabled tool policy from database: %s", exc)
            return []

        disabled_tool_names: List[str] = []
        for row in rows:
            tool_name = getattr(row, "tool_name", None)
            if isinstance(tool_name, str) and tool_name:
                disabled_tool_names.append(tool_name)
        return disabled_tool_names

    def _load_vision_model(self) -> Optional[Any]:
        """通过 model service 读取默认视觉模型。"""
        try:
            from ...web.services.model_service import get_default_vision_model

            return get_default_vision_model(self._user_id)

        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load vision model: {e}")
            return None

    def get_llm(self) -> Optional[Any]:
        """返回显式注入的 LLM。

        这里不再二次兜底查数据库，是因为“工具运行时到底绑定哪个 LLM”
        已经应该在更上层任务装配阶段决定好。
        """
        return self._explicit_llm

    def _load_mcp_server_configs(self) -> List[Dict[str, Any]]:
        """按当前用户读取 MCP server 配置。

        这里明确只返回 `UserMCPServer.is_active = true` 的配置，
        防止后台里存在但当前用户未启用的 server 被误带入运行时。
        """
        logger = logging.getLogger(__name__)
        configs = []

        try:
            from ...web.models.mcp import MCPServer, UserMCPServer

            # Query active MCP servers for this user
            servers = (
                self.db.query(MCPServer)
                .join(UserMCPServer, MCPServer.id == UserMCPServer.mcpserver_id)
                .filter(UserMCPServer.user_id == self._user_id, UserMCPServer.is_active)
                .all()
            )

            logger.info(
                f"Found {len(servers)} active MCP servers for user {self._user_id}"
            )

            for server in servers:
                # Build config dict from server model
                config = {
                    "name": server.name,
                    "transport": server.transport,
                    "description": server.description,
                }

                # Add transport-specific configuration
                transport_config = {}

                if server.transport == "stdio":
                    if server.command:
                        transport_config["command"] = server.command
                    if server.args:
                        transport_config["args"] = server.args
                    if server.env:
                        transport_config["env"] = server.env
                    if server.cwd:
                        transport_config["cwd"] = server.cwd

                elif server.transport in ["sse", "websocket", "streamable_http"]:
                    if server.url:
                        transport_config["url"] = server.url
                    if server.headers:
                        transport_config["headers"] = server.headers

                # Add Docker-specific config if managed internally
                if server.managed == "internal":
                    if server.docker_url:
                        transport_config["docker_url"] = server.docker_url
                    if server.docker_image:
                        transport_config["docker_image"] = server.docker_image
                    if server.docker_environment:
                        transport_config["docker_environment"] = (
                            server.docker_environment
                        )
                    if server.docker_working_dir:
                        transport_config["docker_working_dir"] = (
                            server.docker_working_dir
                        )
                    if server.volumes:
                        transport_config["volumes"] = server.volumes
                    if server.bind_ports:
                        transport_config["bind_ports"] = server.bind_ports
                    if server.restart_policy:
                        transport_config["restart_policy"] = server.restart_policy
                    if server.auto_start is not None:
                        transport_config["auto_start"] = server.auto_start

                config["config"] = transport_config

                # Add user context for MCP tool isolation
                config["user_id"] = str(self._user_id)
                config["allow_users"] = [str(self._user_id)]  # Only allow current user

                configs.append(config)
                logger.debug(
                    f"Loaded MCP server config: {server.name} ({server.transport})"
                )

        except Exception as e:
            logger.warning(f"Failed to load MCP server configs: {e}", exc_info=True)

        logger.info(f"Loaded {len(configs)} MCP server configurations")
        return configs
