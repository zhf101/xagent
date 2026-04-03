"""Helpers to resolve embedding/rerank/llm configs with hub > env fallback priority."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Type, TypeVar, Union

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from xagent.core.model.chat.basic.adapter import create_base_llm
from xagent.core.model.chat.basic.base import BaseLLM
from xagent.core.model.chat.langchain import create_base_chat_model_with_retry
from xagent.core.model.embedding.adapter import create_embedding_adapter
from xagent.core.model.embedding.base import BaseEmbedding
from xagent.core.model.model import (
    ChatModelConfig,
    EmbeddingModelConfig,
    ModelConfig,
    RerankModelConfig,
)
from xagent.core.model.rerank.adapter import create_rerank_adapter
from xagent.core.model.rerank.base import BaseRerank
from xagent.core.model.storage.db.adapter import SQLAlchemyModelHub
from xagent.core.model.storage.db.db_models import create_model_table
from xagent.core.storage.manager import get_default_db_url

from ..core.exceptions import EmbeddingAdapterError, RagCoreException

logger = logging.getLogger(__name__)

# Type variables for generic helper functions
ConfigType = TypeVar("ConfigType", bound=ModelConfig)
AdapterType = TypeVar("AdapterType")
ExceptionType = TypeVar("ExceptionType", bound=RagCoreException)

# Special placeholder values
_PLACEHOLDER_NONE = {"none", ""}


def _env_first(*keys: str) -> Optional[str]:
    """Return the first non-empty environment variable value."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def _is_placeholder_default(model_id: Optional[str]) -> bool:
    """Check if model_id is "default" (case-insensitive)."""
    if model_id is None:
        return False
    return model_id.strip().lower() == "default"


def _is_placeholder_none(model_id: Optional[str]) -> bool:
    """Check if model_id is "none" or empty (case-insensitive)."""
    if model_id is None:
        return True
    normalized = model_id.strip().lower()
    return normalized in _PLACEHOLDER_NONE


def _get_or_init_model_hub() -> Any:
    """Get or create model hub instance directly."""
    try:
        database_url = get_default_db_url()
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False}
            if "sqlite" in database_url
            else {},
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base = declarative_base()
        Model = create_model_table(Base)
        db = SessionLocal()
        Base.metadata.create_all(engine)
        return SQLAlchemyModelHub(db, Model)
    except Exception as e:
        logger.debug(f"Model hub database not available: {e}")
        return None


def _load_model_from_hub(
    model_id: str,
    config_type: Type[ConfigType],
    exception_cls: Type[ExceptionType],
) -> ConfigType:
    """Load model configuration from hub with consistent error handling."""
    hub = _get_or_init_model_hub()
    if hub is None:
        raise exception_cls(
            f"Failed to load {config_type.__name__}: model hub database not available",
            details={"model_id": model_id, "error": "Database not available"},
        )

    try:
        cfg = hub.load(model_id)
    except ValueError as exc:
        raise exception_cls(
            f"Failed to load {config_type.__name__} from model hub",
            details={
                "model_id": model_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        ) from exc

    if not isinstance(cfg, config_type):
        raise exception_cls(
            f"Model '{model_id}' is not a {config_type.__name__}",
            details={"model_id": model_id, "actual_type": type(cfg).__name__},
        )

    return cfg


def _create_adapter_safe(
    cfg: ConfigType,
    adapter_factory: Callable[..., AdapterType],
    exception_cls: Type[ExceptionType],
    context: str = "",
    **adapter_kwargs: Any,
) -> AdapterType:
    """Create adapter with consistent error handling."""
    try:
        return adapter_factory(cfg, **adapter_kwargs)
    except (ImportError, ValueError, TypeError) as exc:
        raise exception_cls(
            f"Failed to create adapter{context}",
            details={"error": str(exc), "error_type": type(exc).__name__},
        ) from exc


def _create_llm_adapter_factory(
    use_langchain_adapter: bool,
) -> Callable[[ChatModelConfig], Union[BaseLLM, "Runnable"]]:
    """Create LLM adapter factory function based on adapter type preference."""

    def adapter_factory(cfg: ChatModelConfig) -> Union[BaseLLM, "Runnable"]:
        if use_langchain_adapter:
            return create_base_chat_model_with_retry(cfg, None)
        else:
            return create_base_llm(cfg)

    return adapter_factory


def resolve_embedding_from_env(
    model_id: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    dimension: Optional[int] = None,
) -> Optional[EmbeddingModelConfig]:
    """Build embedding config from env (OpenAI-compatible)."""
    model = model_id or _env_first("OPENAI_EMBEDDING_MODEL", "DASHSCOPE_EMBEDDING_MODEL")
    key = api_key or _env_first(
        "OPENAI_EMBEDDING_API_KEY",
        "DASHSCOPE_EMBEDDING_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
    )
    base = base_url or _env_first(
        "OPENAI_EMBEDDING_BASE_URL",
        "OPENAI_BASE_URL",
        "DASHSCOPE_EMBEDDING_BASE_URL",
    )
    timeout_val = timeout_sec or _env_first(
        "OPENAI_EMBEDDING_TIMEOUT",
        "OPENAI_TIMEOUT",
        "DASHSCOPE_EMBEDDING_TIMEOUT",
        "DASHSCOPE_TIMEOUT",
    )
    timeout = float(timeout_val) if timeout_val else 180.0
    dim_val = _env_first("OPENAI_EMBEDDING_DIMENSION", "DASHSCOPE_EMBEDDING_DIMENSION")
    dim = dimension if dimension is not None else (int(dim_val) if dim_val else None)

    if model and key:
        return EmbeddingModelConfig(
            id=model,
            model_name=model,
            api_key=key,
            base_url=base,
            timeout=timeout,
            dimension=dim,
            abilities=["embedding"],
        )
    return None


def resolve_rerank_from_env(
    model_id: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    top_n: Optional[int] = None,
) -> Optional[RerankModelConfig]:
    """Build rerank config from env (OpenAI-compatible with legacy fallback)."""
    model = model_id or _env_first("OPENAI_RERANK_MODEL", "DASHSCOPE_RERANK_MODEL")
    key = api_key or _env_first(
        "OPENAI_RERANK_API_KEY",
        "DASHSCOPE_RERANK_API_KEY",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
    )
    base = base_url or _env_first(
        "OPENAI_RERANK_BASE_URL",
        "OPENAI_BASE_URL",
        "DASHSCOPE_RERANK_BASE_URL",
    )
    timeout_val = timeout_sec or _env_first(
        "OPENAI_RERANK_TIMEOUT",
        "OPENAI_TIMEOUT",
        "DASHSCOPE_RERANK_TIMEOUT",
        "DASHSCOPE_TIMEOUT",
    )
    timeout = float(timeout_val) if timeout_val else 180.0
    top_n_val = _env_first("OPENAI_RERANK_TOP_N", "DASHSCOPE_RERANK_TOP_N")
    resolved_top_n = top_n if top_n is not None else (int(top_n_val) if top_n_val else None)

    if model and key:
        return RerankModelConfig(
            id=model,
            model_name=model,
            api_key=key,
            base_url=base,
            timeout=timeout,
            top_n=resolved_top_n,
            abilities=["rerank"],
        )
    return None


def _resolve_adapter_generic(
    model_id: Optional[str],
    config_type: Type[ConfigType],
    exception_type: Type[ExceptionType],
    env_prefix: str,
    model_type_name: str,
    adapter_factory: Callable[..., AdapterType],
    env_resolver: Callable[..., Optional[ConfigType]],
    env_kwargs: dict[str, Any],
    adapter_kwargs: Optional[dict[str, Any]] = None,
) -> Tuple[ConfigType, AdapterType]:
    """Generic helper function for resolving model config/adapter with hub > env fallback priority."""
    adapter_kwargs = adapter_kwargs or {}

    hub = None
    try:
        hub = _get_or_init_model_hub()
    except Exception as hub_error:
        logger.warning(
            f"Model hub not available for {model_type_name}: {hub_error}. "
            "Falling back to environment configuration."
        )

    # Strategy 1: "default" placeholder
    if _is_placeholder_default(model_id) or _is_placeholder_none(model_id):
        if hub is not None:
            try:
                cfg = hub.load("default")
                if isinstance(cfg, config_type):
                    adapter = _create_adapter_safe(
                        cfg, adapter_factory, exception_type, **adapter_kwargs
                    )
                    return cfg, adapter
            except ValueError:
                logger.warning(
                    f"Model 'default' not found in hub for {model_type_name}, falling back to environment"
                )

        env_cfg = env_resolver(**env_kwargs)
        if env_cfg:
            adapter = _create_adapter_safe(
                env_cfg,
                adapter_factory,
                exception_type,
                " from environment configuration",
                **adapter_kwargs,
            )
            return env_cfg, adapter

        raise exception_type(
            f"No {model_type_name} model available: 'default' not found in hub and no environment configuration"
        )

    # Strategy 2: Explicit ID
    else:
        if hub is not None:
            try:
                cfg = hub.load(model_id)
                if isinstance(cfg, config_type):
                    adapter = _create_adapter_safe(
                        cfg, adapter_factory, exception_type, **adapter_kwargs
                    )
                    return cfg, adapter
            except ValueError as hub_error:
                logger.warning(
                    f"Model '{model_id}' not found in hub for {model_type_name}: {hub_error}. "
                    "Falling back to environment configuration."
                )

        env_cfg = env_resolver(**env_kwargs)
        if env_cfg:
            adapter = _create_adapter_safe(
                env_cfg,
                adapter_factory,
                exception_type,
                " from environment configuration",
                **adapter_kwargs,
            )
            return env_cfg, adapter

        raise exception_type(
            f"Model '{model_id}' not found in hub and no environment configuration available for {model_type_name}."
        )


def resolve_embedding_adapter(
    model_id: Optional[str],
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    dimension: Optional[int] = None,
) -> Tuple[EmbeddingModelConfig, BaseEmbedding]:
    """Resolve embedding config/adapter with priority: explicit model_id > hub > env fallback."""
    return _resolve_adapter_generic(
        model_id=model_id,
        config_type=EmbeddingModelConfig,
        exception_type=EmbeddingAdapterError,
        env_prefix="OPENAI_EMBEDDING_",
        model_type_name="embedding",
        adapter_factory=create_embedding_adapter,
        env_resolver=resolve_embedding_from_env,
        env_kwargs={
            "api_key": api_key,
            "base_url": base_url,
            "timeout_sec": timeout_sec,
            "dimension": dimension,
        },
        adapter_kwargs={},
    )


def resolve_rerank_adapter(
    model_id: Optional[str],
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    top_n: Optional[int] = None,
) -> Tuple[RerankModelConfig, BaseRerank]:
    """Resolve rerank config/adapter with priority: explicit model_id > hub > env fallback."""
    return _resolve_adapter_generic(
        model_id=model_id,
        config_type=RerankModelConfig,
        exception_type=RagCoreException,
        env_prefix="OPENAI_RERANK_",
        model_type_name="rerank",
        adapter_factory=create_rerank_adapter,
        env_resolver=resolve_rerank_from_env,
        env_kwargs={
            "api_key": api_key,
            "base_url": base_url,
            "timeout_sec": timeout_sec,
            "top_n": top_n,
        },
        adapter_kwargs={},
    )


def _create_llm_config_from_provider_env(
    env_prefix: str,
    provider_name: str,
    default_model: str,
    *,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Optional[ChatModelConfig]:
    """Create LLM config from environment variables for a specific provider."""
    provider_key = os.getenv(f"{env_prefix}_API_KEY")
    if not provider_key:
        return None

    try:
        final_model_name = model_name or os.getenv(
            f"{env_prefix}_MODEL_NAME", default_model
        )
        final_base_url = base_url or os.getenv(f"{env_prefix}_BASE_URL")
        final_temperature = (
            temperature
            if temperature is not None
            else float(os.getenv(f"{env_prefix}_TEMPERATURE", "0.7"))
        )
        final_max_tokens = (
            max_tokens
            if max_tokens is not None
            else int(os.getenv(f"{env_prefix}_MAX_TOKENS", "4096"))
        )
        final_timeout = (
            timeout_sec
            if timeout_sec is not None
            else float(os.getenv(f"{env_prefix}_TIMEOUT", "180.0"))
        )

        return ChatModelConfig(
            id=final_model_name,
            model_name=final_model_name,
            model_provider=provider_name,
            api_key=api_key or provider_key,
            base_url=final_base_url,
            default_temperature=final_temperature,
            default_max_tokens=final_max_tokens,
            timeout=final_timeout,
            abilities=["chat"],
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to create {provider_name} config from env: {e}")
        return None


def _create_llm_from_env(
    model_name: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Optional[ChatModelConfig]:
    """Build LLM config from environment variables as fallback."""
    return _create_llm_config_from_provider_env(
        "OPENAI",
        "openai",
        "gpt-4",
        model_name=model_name,
        api_key=api_key,
        base_url=base_url,
        timeout_sec=timeout_sec,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def resolve_llm_adapter(
    model_id: Optional[str] = None,
    *,
    use_langchain_adapter: bool = False,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[ChatModelConfig, Union[BaseLLM, "BaseChatModel", "Runnable"]]:
    """Resolve LLM config/adapter with priority: explicit model_id > hub > env fallback."""
    return _resolve_adapter_generic(
        model_id=model_id,
        config_type=ChatModelConfig,
        exception_type=RagCoreException,
        env_prefix="OPENAI_",
        model_type_name="LLM",
        adapter_factory=_create_llm_adapter_factory(use_langchain_adapter),
        env_resolver=_create_llm_from_env,
        env_kwargs={
            "model_name": model_id,
            "api_key": api_key,
            "base_url": base_url,
            "timeout_sec": timeout_sec,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        adapter_kwargs={},
    )
