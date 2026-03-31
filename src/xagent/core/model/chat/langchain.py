"""Model adapter"""

import os
from typing import Any, Callable, Optional, Sequence, Union

from langchain.tools import BaseTool
from langchain_community.chat_models import ChatZhipuAI
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from ...model import ChatModelConfig, ModelConfig
from ...retry import ExponentialBackoff, RetryStrategy, create_retry_wrapper
from .error import retry_on
from .logging_callback import enable_llm_request_logging, configure_http_logging


class ChatModelRetryWrapper(Runnable):
    def __init__(
        self,
        model: BaseChatModel,
        strategy: RetryStrategy,
        max_retries: int = 10,
    ):
        self._retry_wrapper = create_retry_wrapper(
            model,
            Runnable,  # type: ignore[type-abstract]
            retry_methods={"invoke", "ainvoke"},
            strategy=strategy,
            max_retries=max_retries,
            retry_on=retry_on,
        )
        self.model = model
        self.strategy = strategy
        self.max_retries = max_retries

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
    model: ModelConfig, 
    temperature: float | None,
    enable_request_logging: bool = False
) -> BaseChatModel:
    """创建 LangChain Chat Model 实例
    
    将自定义的 LLM 配置适配为对应的 LangChain Chat Model 类。
    
    Args:
        model: 模型配置对象
        temperature: 温度参数，如果为 None 则使用模型默认值
        enable_request_logging: 是否启用请求/响应日志记录（用于调试）
                               如果为 False，会检查环境变量 ENABLE_LLM_LOGGING
        
    Returns:
        配置好的 BaseChatModel 实例
        
    Raises:
        TypeError: 如果模型类型不支持
    """

    if not isinstance(model, ChatModelConfig):
        raise TypeError(f"Unsupported Chat model type: {type(model).__name__}")

    temp = temperature if temperature is not None else model.default_temperature
    
    # 检查是否启用日志记录（优先使用参数，其次检查环境变量）
    if not enable_request_logging:
        enable_request_logging = os.getenv("ENABLE_LLM_LOGGING", "false").lower() == "true"
    
    # 如果启用日志记录，创建 callback handler
    callbacks = [enable_llm_request_logging()] if enable_request_logging else None

    if model.model_provider == "openai":
        return ChatOpenAI(
            model=model.model_name,
            temperature=temp,
            max_tokens=model.default_max_tokens,
            api_key=model.api_key,
            base_url=model.base_url,
            timeout=model.timeout,
            callbacks=callbacks,
        )
    elif model.model_provider in (
        "alibaba-coding-plan",
        "alibaba-coding-plan-cn",
        "zai-coding-plan",
        "zhipuai-coding-plan",
    ):
        return ChatOpenAI(
            model=model.model_name,
            temperature=temp,
            max_tokens=model.default_max_tokens,
            api_key=model.api_key,
            base_url=model.base_url,
            timeout=model.timeout,
            callbacks=callbacks,
        )
    elif model.model_provider == "zhipu":
        return ChatZhipuAI(
            model=model.model_name,
            temperature=temp,
            max_tokens=model.default_max_tokens,
            api_key=model.api_key,
            api_base=model.base_url,
            callbacks=callbacks,
        )
    elif model.model_provider == "azure_openai":
        api_version = os.getenv("OPENAI_API_VERSION", "2024-08-01-preview")
        return AzureChatOpenAI(
            deployment_name=model.model_name,
            azure_endpoint=model.base_url,
            api_key=model.api_key,
            api_version=api_version,
            temperature=temp,
            max_tokens=model.default_max_tokens,
            timeout=model.timeout,
            callbacks=callbacks,
        )
    else:
        raise TypeError(f"Unsupported LLM model provider: {model.model_provider}")


def create_base_chat_model_with_retry(
    model: ModelConfig, 
    temperature: float | None,
    enable_request_logging: bool = False
) -> ChatModelRetryWrapper:
    """创建带重试机制的 Chat Model
    
    Args:
        model: 模型配置对象
        temperature: 温度参数
        enable_request_logging: 是否启用请求/响应日志记录
                               如果为 False，会检查环境变量 ENABLE_LLM_LOGGING
        
    Returns:
        包装了重试机制的 ChatModelRetryWrapper 实例
    """
    chat_model = create_base_chat_model(model, temperature, enable_request_logging)
    strategy = ExponentialBackoff()
    return ChatModelRetryWrapper(chat_model, strategy, max_retries=model.max_retries)


def setup_llm_logging_from_env() -> None:
    """从环境变量配置 LLM 日志记录
    
    在应用启动时调用，配置 LLM 日志记录器和 HTTP 日志。
    
    环境变量：
        ENABLE_LLM_LOGGING: 是否启用 LLM 日志（true/false）
        LLM_LOG_FILE: LLM 日志文件路径（默认: llm_requests.log）
        ENABLE_LLM_HTTP_LOGGING: 是否启用底层 HTTP 日志（true/false）
    """
    import logging
    
    enable_llm_logging = os.getenv("ENABLE_LLM_LOGGING", "false").lower() == "true"
    
    if enable_llm_logging:
        # 配置 LLM 日志文件
        log_file = os.getenv("LLM_LOG_FILE", "llm_requests.log")
        
        # 配置日志记录器
        from logging.handlers import RotatingFileHandler
        
        llm_logger = logging.getLogger("xagent.core.model.chat")
        llm_logger.setLevel(logging.DEBUG)
        
        # 创建文件 handler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        
        # 创建格式化器
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        
        # 添加 handler
        llm_logger.addHandler(file_handler)
        llm_logger.propagate = False
        
        llm_logger.info("LLM 日志记录已启用")
        llm_logger.info(f"日志文件: {log_file}")
        
        # 配置底层 HTTP 日志（可选）
        enable_http_logging = os.getenv("ENABLE_LLM_HTTP_LOGGING", "false").lower() == "true"
        if enable_http_logging:
            configure_http_logging(enable=True, level=logging.DEBUG)
            llm_logger.info("LLM HTTP 日志已启用")
