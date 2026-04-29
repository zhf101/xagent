"""Knowledge base tools registration using @register_tool decorator."""

import logging
from typing import TYPE_CHECKING, Any, List

from .factory import register_tool
from ...core.document_search import list_knowledge_bases, ListKnowledgeBasesArgs

if TYPE_CHECKING:
    from .config import BaseToolConfig

logger = logging.getLogger(__name__)


@register_tool
async def create_knowledge_tools(config: "BaseToolConfig") -> List[Any]:
    """Create knowledge base search tools."""
    tools: List[Any] = []

    try:
        from .document_search import (
            get_knowledge_search_tool,
            get_list_knowledge_bases_tool,
        )

        embedding_model = config.get_embedding_model()
        allowed_collections = config.get_allowed_collections()
        user_id = config.get_user_id()
        is_admin = config.is_admin()

        # Add list knowledge bases tool
        list_tool = get_list_knowledge_bases_tool(
            allowed_collections=allowed_collections,
            user_id=user_id,
            is_admin=is_admin,
        )
        tools.append(list_tool)

        # 检查知识库是否有内容
        has_content = False
        try:
            result = await list_knowledge_bases(
                ListKnowledgeBasesArgs(allowed_collections=allowed_collections),
                user_id=user_id,
                is_admin=is_admin,
            )
            # 检查是否有任何集合包含 embeddings
            for kb in result.knowledge_bases:
                if kb.get("embeddings", 0) > 0:
                    has_content = True
                    break
        except Exception as e:
            logger.warning(f"Failed to check knowledge base content: {e}")
            has_content = False

        # Add search tool
        knowledge_tool = get_knowledge_search_tool(
            embedding_model_id=embedding_model,
            allowed_collections=allowed_collections,
            user_id=user_id,
            is_admin=is_admin,
        )
        #无内容时设置不可用，提示词不拼接工具
        if not has_content:
            knowledge_tool.set_available(False)

        tools.append(knowledge_tool)
    except Exception as e:
        logger.warning(f"Failed to create knowledge tools: {e}")

    return tools
