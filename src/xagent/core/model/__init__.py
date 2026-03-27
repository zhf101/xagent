from .embedding.dashscope import DashScopeEmbedding
from .model import (
    ChatModelConfig,
    EmbeddingModelConfig,
    ImageModelConfig,
    ModelConfig,
    RerankModelConfig,
    SpeechModelConfig,
)
from .tts.base import BaseTTS, TTSResult

try:
    from .tts.adapter import XinferenceTTS, get_tts_model
except Exception:  # 可选依赖缺失时不阻塞整个 web 启动链
    XinferenceTTS = None  # type: ignore[assignment]

    def get_tts_model(*args, **kwargs):  # type: ignore[no-redef]
        raise ImportError(
            "Xinference TTS dependencies are not installed. "
            "Install xinference or xinference-client to use TTS models."
        )

__all__ = [
    "ModelConfig",
    "ChatModelConfig",
    "ImageModelConfig",
    "RerankModelConfig",
    "EmbeddingModelConfig",
    "SpeechModelConfig",
    "DashScopeEmbedding",
    "BaseTTS",
    "TTSResult",
    "XinferenceTTS",
    "get_tts_model",
]
