from ....model import ChatModelConfig, ModelConfig
from ....retry import create_retry_wrapper
from ..error import retry_on
from .base import BaseLLM
from .openai import OpenAILLM


def create_base_llm(model: ModelConfig) -> BaseLLM:
    """
    Creates a custom BaseLLM instance from a ModelConfig.
    
    Only supports OpenAI-compatible API format. All providers use OpenAILLM
    with different base_url configurations.
    """
    if not isinstance(model, ChatModelConfig):
        raise TypeError(f"Invalid model type: {type(model).__name__}")

    # All providers use OpenAI-compatible API
    llm: BaseLLM = OpenAILLM(
        model_name=model.model_name,
        api_key=model.api_key,
        base_url=model.base_url,
        default_temperature=model.default_temperature,
        default_max_tokens=model.default_max_tokens,
        timeout=model.timeout,
        abilities=model.abilities,
    )

    return create_retry_wrapper(
        llm,
        BaseLLM,  # type: ignore[type-abstract]
        retry_methods={"chat", "vision_chat", "stream_chat"},
        retry_on=retry_on,
    )