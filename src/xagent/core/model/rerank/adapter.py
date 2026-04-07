from collections.abc import Sequence
from typing import Optional

import requests

from ...retry import create_retry_wrapper
from ..model import RerankModelConfig
from .base import BaseRerank


def retry_on(e: Exception) -> bool:
    ERRORS = requests.exceptions.Timeout

    if isinstance(e, requests.exceptions.HTTPError):
        status_code = e.response.status_code
        return status_code == 429 or 500 <= status_code < 600  # 429 and 5xx
    return isinstance(e, ERRORS)


def create_rerank_adapter(model_config: RerankModelConfig) -> BaseRerank:
    """
    Creates a custom BaseRerank instance from a RerankModelConfig.

    Only OpenAI-compatible rerank endpoints are allowed on this branch.
    """
    return create_retry_wrapper(
        RerankModelAdapter(model_config),
        BaseRerank,  # type: ignore[type-abstract]
        retry_methods={"compress"},
        max_retries=model_config.max_retries,
        retry_on=retry_on,
    )


class RerankModelAdapter(BaseRerank):
    """Adapter for OpenAI-compatible rerank API."""

    def __init__(self, model_config: RerankModelConfig):
        self.model_config = model_config
        self._rerank_model = self._create_rerank_model()

    def _create_rerank_model(self) -> BaseRerank:
        """Create the actual rerank model from configuration."""
        if self.model_config.model_provider.lower().strip() != "openai":
            raise ValueError(
                f"Unsupported model provider: {self.model_config.model_provider}"
            )

        return OpenAIRerank(
            model=self.model_config.model_name,
            api_key=self.model_config.api_key,
            base_url=self.model_config.base_url,
            top_n=self.model_config.top_n,
        )

    def compress(
        self,
        documents: Sequence[str],
        query: str,
    ) -> Sequence[str]:
        """Rerank documents using the underlying rerank model."""
        return self._rerank_model.compress(documents, query)


class OpenAIRerank(BaseRerank):
    """OpenAI-compatible rerank model."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        top_n: Optional[int] = None,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.top_n = top_n

    def compress(
        self,
        documents: Sequence[str],
        query: str,
    ) -> Sequence[str]:
        """Rerank documents using OpenAI-compatible rerank API."""
        url = f"{self.base_url}/rerank"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
        }
        if self.top_n is not None:
            payload["top_n"] = self.top_n

        response = requests.post(url, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])

        ordered_indices = [item["index"] for item in results if "index" in item]
        return [documents[index] for index in ordered_indices if index < len(documents)]
