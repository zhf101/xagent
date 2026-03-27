import os

from ....model import ChatModelConfig, ModelConfig
from ....retry import create_retry_wrapper
from ..error import retry_on
from .base import BaseLLM


def create_base_llm(model: ModelConfig) -> BaseLLM:
    """
    Creates a custom BaseLLM instance from a ModelConfig.
    """
    if not isinstance(model, ChatModelConfig):
        raise TypeError(f"Invalid model type: {type(model).__name__}")

    if model.model_provider == "openai":
        from .openai import OpenAILLM

        llm: BaseLLM = OpenAILLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider in (
        "alibaba-coding-plan",
        "alibaba-coding-plan-cn",
        "zai-coding-plan",
        "zhipuai-coding-plan",
    ):
        from .openai import OpenAILLM

        llm = OpenAILLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider in (
        "minimax-coding-plan",
        "minimax-cn-coding-plan",
        "kimi-for-coding",
    ):
        from .claude import ClaudeLLM

        llm = ClaudeLLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider == "azure_openai":
        from .azure_openai import AzureOpenAILLM

        llm = AzureOpenAILLM(
            model_name=model.model_name,
            azure_endpoint=model.base_url,  # Reuse base_url as azure_endpoint
            api_key=model.api_key,
            api_version=os.getenv("OPENAI_API_VERSION", "2024-08-01-preview"),
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider == "zhipu":
        from .zhipu import ZhipuLLM

        llm = ZhipuLLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider == "gemini":
        from .gemini import GeminiLLM

        llm = GeminiLLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider == "claude":
        from .claude import ClaudeLLM

        llm = ClaudeLLM(
            model_name=model.model_name,
            api_key=model.api_key,
            base_url=model.base_url,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    elif model.model_provider == "xinference":
        from .xinference import XinferenceLLM

        llm = XinferenceLLM(
            model_name=model.model_name,
            base_url=model.base_url,
            api_key=model.api_key,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            abilities=model.abilities,
        )
    else:
        raise TypeError(f"Unsupported LLM model type: {model.model_provider}")

    return create_retry_wrapper(
        llm,
        BaseLLM,  # type: ignore[type-abstract]
        retry_methods={"chat", "vision_chat", "stream_chat"},
        retry_on=retry_on,
    )
