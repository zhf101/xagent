from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .core import MemoryNote, MemoryResponse


class MemoryStore(ABC):
    """
    Abstract base class defining the interface for a memory storage backend.

    Any concrete implementation (e.g., in-memory store, ChromaDB, Redis, etc.)
    should implement all the following methods to manage MemoryNote objects.
    """

    @abstractmethod
    def add(self, note: "MemoryNote") -> "MemoryResponse":
        """
        Add a memory note to the store.

        Args:
            note (MemoryNote): The memory note to be added.

        Returns:
            MemoryResponse: Response indicating success and the note ID.
        """
        pass

    @abstractmethod
    def get(self, note_id: str) -> "MemoryResponse":
        """
        Retrieve a memory note by its ID.

        Args:
            note_id (str): The unique identifier of the memory note.

        Returns:
            MemoryResponse: Response containing the memory note or an error.
        """
        pass

    @abstractmethod
    def update(self, note: "MemoryNote") -> "MemoryResponse":
        """
        Update an existing memory note.

        Args:
            note (MemoryNote): The memory note with updated data.

        Returns:
            MemoryResponse: Response indicating success or failure.
        """
        pass

    @abstractmethod
    def delete(self, note_id: str) -> "MemoryResponse":
        """
        Delete a memory note by its ID.

        Args:
            note_id (str): The unique identifier of the memory note.

        Returns:
            MemoryResponse: Response indicating success or failure.
        """
        pass

    @abstractmethod
    def search(
        self,
        query: str,
        k: int = 5,
        filters: Optional[dict[str, Any]] = None,
        similarity_threshold: Optional[float] = None,
    ) -> list["MemoryNote"]:
        """
        Search memory notes by query text with optional filters.

        Args:
            query (str): The query string to search for.
            k (int, optional): Number of top results to return. Defaults to 5.
            filters (Dict[str, Any], optional): Additional filter criteria. Defaults to None.

        Returns:
            List[MemoryNote]: List of matching memory notes.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clear all memory notes from the store.
        """
        pass

    @abstractmethod
    def list_all(
        self,
        filters: Optional[dict[str, Any]] = None,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List["MemoryNote"]:
        """
        List memory notes with optional filtering and pagination.

        Args:
            filters (Dict[str, Any], optional): Filter criteria like category, date range, etc.
            limit (int, optional): Maximum number of records to return. ``None`` means no limit.
            offset (int, optional): Number of matching records to skip. Defaults to 0.

        Returns:
            List[MemoryNote]: List of memory notes matching the filters.
        """
        pass

    @abstractmethod
    def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """
        Count memory notes matching optional filters.

        Args:
            filters (Dict[str, Any], optional): Filter criteria like category, date range, etc.

        Returns:
            int: Number of memory notes matching the filters.
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about the memory store.

        Returns:
            Dict[str, Any]: Statistics including total count, counts by category, etc.
        """
        pass
