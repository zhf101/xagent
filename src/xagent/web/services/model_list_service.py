"""Service to fetch available models from supported providers."""

import logging
from typing import Any, Dict, List, Optional

from ...core.model.providers import default_base_url_for_provider, get_supported_provider_metadata
from ...core.utils.security import redact_sensitive_text

logger = logging.getLogger(__name__)


def _static_model_list(models: tuple[str, ...], owned_by: str) -> List[Dict[str, Any]]:
    return [{"id": model_id, "created": 0, "owned_by": owned_by} for model_id in models]


async def fetch_openai_models(
    api_key: str, base_url: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Fetch available models from OpenAI using OpenAILLM.list_available_models().

    Args:
        api_key: OpenAI API key
        base_url: Custom base URL (optional)

    Returns:
        List of available models with their information
    """
    from ...core.model.chat.basic.openai import OpenAILLM

    return await OpenAILLM.list_available_models(api_key, base_url)


# Provider registry mapping provider names to their fetch functions
PROVIDER_FETCHERS: Dict[str, Any] = {
    "openai": fetch_openai_models,
}


async def fetch_models_from_provider(
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch available models from a specific provider.

    Args:
        provider: Provider name (openai)
        api_key: API key for the provider
        base_url: Custom base URL (optional)

    Returns:
        List of available models
    """
    provider_id = provider.lower()
    fetcher = PROVIDER_FETCHERS.get(provider_id)

    if not fetcher:
        logger.warning(f"Unknown provider: {provider}")
        return []

    try:
        resolved_base_url = base_url or default_base_url_for_provider(provider_id)
        result: List[Dict[str, Any]] = await fetcher(api_key, resolved_base_url)
        return result
    except Exception as e:
        logger.error(
            "Error fetching models from %s: %s",
            provider,
            redact_sensitive_text(str(e)),
        )
        raise


def get_supported_providers() -> List[Dict[str, Any]]:
    """Get list of supported providers.

    Returns:
        List of provider information
    """
    return get_supported_provider_metadata()
