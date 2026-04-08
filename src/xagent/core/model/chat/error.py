import httpx
import openai

from ..retry_config import DEFAULT_LLM_MAX_RETRIES, MAX_LLM_MAX_RETRIES, normalize_llm_retry_count
from .exceptions import LLMRetryableError

try:
    from zai.core._errors import APIStatusError as ZaiAPIStatusError  # type: ignore
except ImportError:
    ZaiAPIStatusError = None


def retry_on(e: Exception) -> bool:
    ERRORS = (
        httpx.TimeoutException,
        httpx.NetworkError,
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.APITimeoutError,
    )

    def _is_retryable(exc: BaseException) -> bool:
        # Handle LLM-specific retryable errors
        # These are explicitly marked as retryable by the LLM implementation
        if isinstance(exc, LLMRetryableError):
            return True

        # Handle httpx errors
        if isinstance(exc, httpx.HTTPStatusError):
            return (
                exc.response.status_code == 429 or 500 <= exc.response.status_code < 600
            )

        # Handle Zai/Zhipu SDK errors
        if ZaiAPIStatusError and isinstance(exc, ZaiAPIStatusError):
            return bool(exc.status_code == 429 or 500 <= exc.status_code < 600)

        return isinstance(exc, ERRORS)

    if _is_retryable(e):
        return True

    # Check the underlying cause (fix for RuntimeError wrapping)
    if e.__cause__ and _is_retryable(e.__cause__):
        return True

    return False
