from .adapter import create_embedding_adapter
from .base import BaseEmbedding
from .openai import OpenAIEmbedding

# Backward-compatible alias for modules that still import DashScopeEmbedding.
DashScopeEmbedding = OpenAIEmbedding

__all__ = [
    "BaseEmbedding",
    "OpenAIEmbedding",
    "DashScopeEmbedding",
    "create_embedding_adapter",
]
