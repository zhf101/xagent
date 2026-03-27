"""Text-to-Speech (TTS) model implementations."""

from .base import BaseTTS, TTSResult

try:
    from .adapter import XinferenceTTS, get_tts_model
except Exception:  # 可选依赖缺失时不要阻塞整体导入
    XinferenceTTS = None  # type: ignore[assignment]

    def get_tts_model(*args, **kwargs):  # type: ignore[no-redef]
        raise ImportError(
            "Xinference TTS dependencies are not installed. "
            "Install xinference or xinference-client to use TTS models."
        )

__all__ = [
    "get_tts_model",
    "BaseTTS",
    "TTSResult",
    "XinferenceTTS",
]
