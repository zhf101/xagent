from typing import Any, Optional


def _normalize_provider(provider: str) -> str:
    return provider.lower().strip()


def canonical_provider_name(provider: str) -> str:
    """Return canonical provider name."""
    return _normalize_provider(provider)


def default_base_url_for_provider(provider: str) -> Optional[str]:
    """Return default base URL for provider if available."""
    _ = provider
    return None


def curated_models_for_provider(provider: str) -> tuple[str, ...]:
    """Return curated models for provider if available."""
    _ = provider
    return ()


def provider_compatibility_for_provider(provider: str) -> Optional[str]:
    """All supported providers use OpenAI-compatible API format."""
    _ = provider
    return "openai_compatible"


_SUPPORTED_PROVIDER_METADATA: tuple[dict[str, Any], ...] = (
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "OpenAI API compatible models",
        "requires_base_url": False,
        "compatibility": "openai_compatible",
    },
)


def get_supported_provider_metadata() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for provider in _SUPPORTED_PROVIDER_METADATA:
        provider_info = dict(provider)
        default_base_url = default_base_url_for_provider(provider_info["id"])
        if default_base_url is not None:
            provider_info["default_base_url"] = default_base_url
        providers.append(provider_info)
    return providers
