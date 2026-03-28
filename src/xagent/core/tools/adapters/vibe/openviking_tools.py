"""OpenViking 上下文工具。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Mapping, Type

from pydantic import BaseModel, Field

from .....integrations.openviking import get_openviking_service
from .base import AbstractBaseTool, ToolCategory, ToolVisibility
from .factory import register_tool

if TYPE_CHECKING:
    from .config import BaseToolConfig

logger = logging.getLogger(__name__)


class OpenVikingSearchArgs(BaseModel):
    query: str = Field(description="要检索的自然语言查询")
    target_uri: str = Field(
        default="",
        description="限定检索范围的 Viking URI，例如 viking://user/memories/",
    )
    limit: int = Field(default=5, ge=1, le=20, description="返回结果条数")
    score_threshold: float | None = Field(
        default=None,
        description="可选相似度阈值，越严格命中越少",
    )
    session_id: str | None = Field(
        default=None,
        description="可选 OpenViking session_id；提供后会使用带会话上下文的搜索",
    )


class OpenVikingSearchResult(BaseModel):
    result: Any = Field(description="OpenViking 返回的原始检索结果")


class OpenVikingReadContextArgs(BaseModel):
    uri: str = Field(description="要读取的 Viking URI")
    level: str = Field(
        default="overview",
        description="读取层级：abstract / overview / read",
    )
    offset: int = Field(default=0, ge=0, description="read 模式下的起始偏移")
    limit: int = Field(default=-1, description="read 模式下的读取行数")


class OpenVikingReadContextResult(BaseModel):
    level: str = Field(description="实际读取层级")
    content: Any = Field(description="OpenViking 返回的上下文内容")


class OpenVikingListTreeArgs(BaseModel):
    uri: str = Field(default="viking://", description="要查看的 Viking URI 根路径")
    output: str = Field(
        default="original",
        description="OpenViking tree 输出格式，默认 original",
    )
    abs_limit: int = Field(default=128, ge=1, le=512, description="摘要长度限制")
    show_all_hidden: bool = Field(
        default=False,
        description="是否显示隐藏节点",
    )
    node_limit: int = Field(default=1000, ge=1, le=5000, description="最大节点数")


class OpenVikingListTreeResult(BaseModel):
    tree: Any = Field(description="OpenViking 返回的资源树结果")


class OpenVikingGrepArgs(BaseModel):
    uri: str = Field(description="要检索内容的 Viking URI 范围")
    pattern: str = Field(description="要查找的文本模式")
    case_insensitive: bool = Field(
        default=False,
        description="是否忽略大小写",
    )
    node_limit: int | None = Field(
        default=None,
        ge=1,
        le=5000,
        description="可选最大节点扫描数",
    )


class OpenVikingGrepResult(BaseModel):
    result: Any = Field(description="OpenViking 返回的 grep 结果")


class OpenVikingGlobArgs(BaseModel):
    pattern: str = Field(
        description="路径匹配模式，例如 **/*.md 或 **/README*"
    )
    uri: str = Field(
        default="viking://",
        description="限定匹配范围的 Viking URI 根路径",
    )


class OpenVikingGlobResult(BaseModel):
    result: Any = Field(description="OpenViking 返回的 glob 结果")


class OpenVikingSearchTool(AbstractBaseTool):
    category = ToolCategory.KNOWLEDGE

    def __init__(self, *, user_id: int, agent_id: str | None = None):
        self._visibility = ToolVisibility.PUBLIC
        self._user_id = user_id
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "openviking_search"

    @property
    def description(self) -> str:
        return (
            "Search context from OpenViking. "
            "Use this when you need long-term memory, indexed resources, or "
            "hierarchical context beyond the built-in knowledge base."
        )

    @property
    def tags(self) -> list[str]:
        return ["openviking", "context", "memory", "knowledge", "search"]

    def args_type(self) -> Type[BaseModel]:
        return OpenVikingSearchArgs

    def return_type(self) -> Type[BaseModel]:
        return OpenVikingSearchResult

    def run_json_sync(self, args: Mapping[str, Any]) -> Any:
        raise NotImplementedError("OpenVikingSearchTool only supports async execution.")

    async def run_json_async(self, args: Mapping[str, Any]) -> Any:
        tool_args = OpenVikingSearchArgs.model_validate(args)
        service = get_openviking_service()
        if not service.search_is_enabled():
            raise RuntimeError("OpenViking search is not enabled")

        if tool_args.session_id:
            result = await service.search(
                user_id=self._user_id,
                agent_id=self._agent_id,
                query=tool_args.query,
                target_uri=tool_args.target_uri,
                session_id=tool_args.session_id,
                limit=tool_args.limit,
                score_threshold=tool_args.score_threshold,
            )
        else:
            result = await service.find(
                user_id=self._user_id,
                agent_id=self._agent_id,
                query=tool_args.query,
                target_uri=tool_args.target_uri,
                limit=tool_args.limit,
                score_threshold=tool_args.score_threshold,
            )

        return OpenVikingSearchResult(result=result).model_dump()


class OpenVikingReadContextTool(AbstractBaseTool):
    category = ToolCategory.KNOWLEDGE

    def __init__(self, *, user_id: int, agent_id: str | None = None):
        self._visibility = ToolVisibility.PUBLIC
        self._user_id = user_id
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "openviking_read_context"

    @property
    def description(self) -> str:
        return (
            "Read layered context from OpenViking. "
            "Prefer abstract or overview before reading full content to control token usage."
        )

    @property
    def tags(self) -> list[str]:
        return ["openviking", "context", "read", "overview", "abstract"]

    def args_type(self) -> Type[BaseModel]:
        return OpenVikingReadContextArgs

    def return_type(self) -> Type[BaseModel]:
        return OpenVikingReadContextResult

    def run_json_sync(self, args: Mapping[str, Any]) -> Any:
        raise NotImplementedError(
            "OpenVikingReadContextTool only supports async execution."
        )

    async def run_json_async(self, args: Mapping[str, Any]) -> Any:
        tool_args = OpenVikingReadContextArgs.model_validate(args)
        service = get_openviking_service()
        if not service.search_is_enabled():
            raise RuntimeError("OpenViking context read is not enabled")

        content = await service.read_context(
            user_id=self._user_id,
            agent_id=self._agent_id,
            uri=tool_args.uri,
            level=tool_args.level,
            offset=tool_args.offset,
            limit=tool_args.limit,
        )
        return OpenVikingReadContextResult(
            level=tool_args.level,
            content=content,
        ).model_dump()


class OpenVikingListTreeTool(AbstractBaseTool):
    category = ToolCategory.KNOWLEDGE

    def __init__(self, *, user_id: int, agent_id: str | None = None):
        self._visibility = ToolVisibility.PUBLIC
        self._user_id = user_id
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "openviking_list_tree"

    @property
    def description(self) -> str:
        return (
            "Browse OpenViking resource tree. "
            "Use this to understand the hierarchy of resources, memories, or skills "
            "before reading specific nodes."
        )

    @property
    def tags(self) -> list[str]:
        return ["openviking", "context", "tree", "filesystem", "browse"]

    def args_type(self) -> Type[BaseModel]:
        return OpenVikingListTreeArgs

    def return_type(self) -> Type[BaseModel]:
        return OpenVikingListTreeResult

    def run_json_sync(self, args: Mapping[str, Any]) -> Any:
        raise NotImplementedError(
            "OpenVikingListTreeTool only supports async execution."
        )

    async def run_json_async(self, args: Mapping[str, Any]) -> Any:
        tool_args = OpenVikingListTreeArgs.model_validate(args)
        service = get_openviking_service()
        if not service.search_is_enabled():
            raise RuntimeError("OpenViking tree browsing is not enabled")

        tree = await service.tree(
            user_id=self._user_id,
            agent_id=self._agent_id,
            uri=tool_args.uri,
            output=tool_args.output,
            abs_limit=tool_args.abs_limit,
            show_all_hidden=tool_args.show_all_hidden,
            node_limit=tool_args.node_limit,
        )
        return OpenVikingListTreeResult(tree=tree).model_dump()


class OpenVikingGrepTool(AbstractBaseTool):
    category = ToolCategory.KNOWLEDGE

    def __init__(self, *, user_id: int, agent_id: str | None = None):
        self._visibility = ToolVisibility.PUBLIC
        self._user_id = user_id
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "openviking_grep"

    @property
    def description(self) -> str:
        return (
            "Search literal text inside OpenViking resources. "
            "Use this when you already know a keyword or snippet and need exact matches."
        )

    @property
    def tags(self) -> list[str]:
        return ["openviking", "context", "grep", "search", "text"]

    def args_type(self) -> Type[BaseModel]:
        return OpenVikingGrepArgs

    def return_type(self) -> Type[BaseModel]:
        return OpenVikingGrepResult

    def run_json_sync(self, args: Mapping[str, Any]) -> Any:
        raise NotImplementedError("OpenVikingGrepTool only supports async execution.")

    async def run_json_async(self, args: Mapping[str, Any]) -> Any:
        tool_args = OpenVikingGrepArgs.model_validate(args)
        service = get_openviking_service()
        if not service.search_is_enabled():
            raise RuntimeError("OpenViking grep is not enabled")

        result = await service.grep(
            user_id=self._user_id,
            agent_id=self._agent_id,
            uri=tool_args.uri,
            pattern=tool_args.pattern,
            case_insensitive=tool_args.case_insensitive,
            node_limit=tool_args.node_limit,
        )
        return OpenVikingGrepResult(result=result).model_dump()


class OpenVikingGlobTool(AbstractBaseTool):
    category = ToolCategory.KNOWLEDGE

    def __init__(self, *, user_id: int, agent_id: str | None = None):
        self._visibility = ToolVisibility.PUBLIC
        self._user_id = user_id
        self._agent_id = agent_id

    @property
    def name(self) -> str:
        return "openviking_glob"

    @property
    def description(self) -> str:
        return (
            "Match OpenViking paths by glob pattern. "
            "Use this to find files or directories when you know the naming pattern."
        )

    @property
    def tags(self) -> list[str]:
        return ["openviking", "context", "glob", "filesystem", "search"]

    def args_type(self) -> Type[BaseModel]:
        return OpenVikingGlobArgs

    def return_type(self) -> Type[BaseModel]:
        return OpenVikingGlobResult

    def run_json_sync(self, args: Mapping[str, Any]) -> Any:
        raise NotImplementedError("OpenVikingGlobTool only supports async execution.")

    async def run_json_async(self, args: Mapping[str, Any]) -> Any:
        tool_args = OpenVikingGlobArgs.model_validate(args)
        service = get_openviking_service()
        if not service.search_is_enabled():
            raise RuntimeError("OpenViking glob is not enabled")

        result = await service.glob(
            user_id=self._user_id,
            agent_id=self._agent_id,
            pattern=tool_args.pattern,
            uri=tool_args.uri,
        )
        return OpenVikingGlobResult(result=result).model_dump()


@register_tool
async def create_openviking_tools(config: "BaseToolConfig") -> List[Any]:
    """按配置创建 OpenViking 工具。"""

    service = get_openviking_service()
    if not service.search_is_enabled():
        return []

    user_id = config.get_user_id()
    if user_id is None:
        logger.warning("OpenViking tools skipped because user_id is unavailable")
        return []

    task_id = config.get_task_id()
    agent_id = str(task_id) if task_id else service.settings.default_agent

    return [
        OpenVikingSearchTool(user_id=int(user_id), agent_id=agent_id),
        OpenVikingReadContextTool(user_id=int(user_id), agent_id=agent_id),
        OpenVikingListTreeTool(user_id=int(user_id), agent_id=agent_id),
        OpenVikingGrepTool(user_id=int(user_id), agent_id=agent_id),
        OpenVikingGlobTool(user_id=int(user_id), agent_id=agent_id),
    ]
