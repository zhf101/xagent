from ....model import ChatModelConfig, ModelConfig
from ....retry import create_retry_wrapper
from ..error import normalize_llm_retry_count, retry_on
from .base import BaseLLM
from .openai import OpenAILLM


def create_base_llm(model: ModelConfig) -> BaseLLM:
    """
    根据 ModelConfig 构造基础 LLM，并统一挂上重试包装。

    这里是本次“LLM 不可达不要无限空转”的关键入口之一：
    1. 数据库/前端传来的 `max_retries` 可能为空、非法或过大。
    2. 如果这里不显式传给 `create_retry_wrapper`，就会退回 wrapper 自身默认值，
       导致模型配置看起来生效，实际上没有真正接入执行链。
    3. 所以必须在这里做统一归一化后再传递，确保所有基础 LLM 都遵守同一套上限。
    """
    if not isinstance(model, ChatModelConfig):
        raise TypeError(f"Invalid model type: {type(model).__name__}")

    if model.model_provider != "openai":
        raise TypeError(f"Unsupported LLM model type: {model.model_provider}")

    llm: BaseLLM = OpenAILLM(
        model_name=model.model_name,
        api_key=model.api_key,
        base_url=model.base_url,
        default_temperature=model.default_temperature,
        default_max_tokens=model.default_max_tokens,
        timeout=model.timeout,
        abilities=model.abilities,
    )
    normalized_max_retries = normalize_llm_retry_count(model.max_retries)

    return create_retry_wrapper(
        llm,
        BaseLLM,  # type: ignore[type-abstract]
        retry_methods={"chat", "vision_chat", "stream_chat"},
        max_retries=normalized_max_retries,
        retry_on=retry_on,
    )
