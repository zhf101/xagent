"""Model adapter"""

from typing import Any, Callable, Optional, Sequence, Union

from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI

from ...model import ChatModelConfig, ModelConfig
from ...retry import ExponentialBackoff, RetryStrategy, create_retry_wrapper
from .error import normalize_llm_retry_count, retry_on
from .logging_callback import (
    enable_llm_request_logging,
    is_llm_logging_enabled,
    setup_llm_logging_from_env,
)


class ChatModelRetryWrapper(Runnable):
    def __init__(
        self,
        model: BaseChatModel,
        strategy: RetryStrategy,
        max_retries: int = 10,
    ):
        normalized_max_retries = normalize_llm_retry_count(max_retries)
        self._retry_wrapper = create_retry_wrapper(
            model,
            Runnable,  # type: ignore[type-abstract]
            retry_methods={"invoke", "ainvoke"},
            strategy=strategy,
            max_retries=normalized_max_retries,
            retry_on=retry_on,
        )
        self.model = model
        self.strategy = strategy
        self.max_retries = normalized_max_retries

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> Any:
        return self._retry_wrapper.invoke(input, config, **kwargs)

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> Any:
        return await self._retry_wrapper.ainvoke(input, config, **kwargs)

    def bind_tools(
        self,
        tools: Sequence[
            Union[dict[str, Any], type, Callable, BaseTool]  # noqa: UP006
        ],
        *,
        tool_choice: Optional[Union[str]] = None,
        **kwargs: Any,
    ) -> Runnable:
        model = self.model.bind_tools(tools)
        return create_retry_wrapper(
            model,
            Runnable,  # type: ignore[type-abstract]
            retry_methods={"invoke", "ainvoke"},
            strategy=self.strategy,
            max_retries=self.max_retries,
            retry_on=retry_on,
        )

    def with_structured_output(
        self,
        schema: Union[dict, type],  # noqa: UP006
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable:  # noqa: UP006
        model = self.model.with_structured_output(schema)
        return create_retry_wrapper(
            model,
            Runnable,  # type: ignore[type-abstract]
            retry_methods={"invoke", "ainvoke"},
            strategy=self.strategy,
            max_retries=self.max_retries,
            retry_on=retry_on,
        )


def create_base_chat_model(
    model: ModelConfig, temperature: float | None
) -> BaseChatModel:
    """
    Adapts a custom LLM instance to its corresponding LangChain Chat Model class
    """

    if not isinstance(model, ChatModelConfig):
        raise TypeError(f"Unsupported Chat model type: {type(model).__name__}")

    temp = temperature if temperature is not None else model.default_temperature
    callbacks = None
    if is_llm_logging_enabled():
        setup_llm_logging_from_env()
        callbacks = [enable_llm_request_logging()]

    if model.model_provider != "openai":
        raise TypeError(f"Unsupported LLM model provider: {model.model_provider}")

    return ChatOpenAI(
        model=model.model_name,
        temperature=temp,
        max_tokens=model.default_max_tokens,
        api_key=model.api_key,
        base_url=model.base_url,
        timeout=model.timeout,
        callbacks=callbacks,
    )


def create_base_chat_model_with_retry(
    model: ModelConfig, temperature: float | None
) -> ChatModelRetryWrapper:
    chat_model = create_base_chat_model(model, temperature)
    strategy = ExponentialBackoff()
    return ChatModelRetryWrapper(chat_model, strategy, max_retries=model.max_retries)
