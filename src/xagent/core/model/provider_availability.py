"""Provider availability module.

Since all models now use OpenAI-compatible API format, 
provider availability checks are no longer needed.
"""


def is_provider_disabled(provider: str) -> bool:
    """Check if a provider is disabled. Always returns False since all use OpenAI format."""
    return False


def disabled_provider_message(provider: str) -> str:
    """Return disabled provider message. Not used anymore."""
    return f"Provider '{provider}' is not available."


def ensure_provider_enabled(provider: str) -> None:
    """Ensure provider is enabled. No-op since all providers use OpenAI format."""
    pass