from abc import ABC, abstractmethod
from collections.abc import Sequence


class BaseRerank(ABC):
    """Abstract base class for rerank models."""

    @abstractmethod
    def compress(
        self,
        documents: Sequence[str],
        query: str,
    ) -> Sequence[str]:
        """
        Rerank documents based on relevance to query.

        Args:
            documents: List of document texts to rerank
            query: Query text for relevance scoring

        Returns:
            Reranked list of document texts
        """
        pass
