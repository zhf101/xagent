from typing import Any, Optional

# 当前分支只保留 OpenAI 兼容格式，请求目标可以通过自定义 base_url 指向任意兼容网关。
_PROVIDER_ALIASES: dict[str, str] = {}

_DEFAULT_BASE_URL_BY_PROVIDER: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
}

_CURATED_MODELS_BY_PROVIDER: dict[str, tuple[str, ...]] = {}

_SUPPORTED_PROVIDER_METADATA: tuple[dict[str, Any], ...] = (
    {
        "id": "openai",
        "name": "OpenAI Compatible",
        "description": "OpenAI API compatible models",
        "requires_base_url": False,
        "compatibility": "openai_compatible",
    },
)


def _normalize_provider(provider: str) -> str:
    return provider.lower().strip()


def canonical_provider_name(provider: str) -> str:
    normalized = _normalize_provider(provider)
    return _PROVIDER_ALIASES.get(normalized, normalized)


def default_base_url_for_provider(provider: str) -> Optional[str]:
    return _DEFAULT_BASE_URL_BY_PROVIDER.get(canonical_provider_name(provider))


def curated_models_for_provider(provider: str) -> tuple[str, ...]:
    return _CURATED_MODELS_BY_PROVIDER.get(canonical_provider_name(provider), ())


def provider_compatibility_for_provider(provider: str) -> Optional[str]:
    provider_id = canonical_provider_name(provider)
    for provider_info in _SUPPORTED_PROVIDER_METADATA:
        if provider_info["id"] == provider_id:
            compatibility = provider_info.get("compatibility")
            return str(compatibility) if compatibility is not None else None
    return None


def get_supported_provider_metadata() -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    for provider in _SUPPORTED_PROVIDER_METADATA:
        provider_info = dict(provider)
        default_base_url = default_base_url_for_provider(provider_info["id"])
        if default_base_url is not None:
            provider_info["default_base_url"] = default_base_url
        providers.append(provider_info)
    return providers
