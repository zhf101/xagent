from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional


class VectorStore(ABC):
    """
    向量存储 provider 的抽象基类。

    该接口定义了添加、删除和搜索向量嵌入的基本方法，
    并支持可选的元数据过滤。
    """

    support_store_texts: ClassVar[Optional[bool]] = None

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if cls.support_store_texts is None:
            raise TypeError(
                f"Class {cls.__name__} must define 'support_store_texts' class attribute"
            )

    @abstractmethod
    def add_vectors(
        self,
        vectors: List[List[float]],
        ids: Optional[List[str]] = None,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        向存储中添加向量。

        参数:
            vectors: 要添加的向量列表。
            ids: 每个向量对应的 ID 列表（可选）。如未提供，应自动生成 ID。
            metadatas: 与每个向量关联的元数据字典列表（可选）。

        返回:
            已存储到向量库中的向量 ID 列表。
        """
        pass

    @abstractmethod
    def delete_vectors(self, ids: List[str]) -> bool:
        """
        按 ID 从存储中删除向量。

        参数:
            ids: 要删除的向量 ID 列表。

        返回:
            删除成功返回 True，否则返回 False。
        """
        pass

    @abstractmethod
    def search_vectors(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        搜索与查询向量相似的向量。

        参数:
            query_vector: 用于搜索的向量。
            top_k: 返回的最相似向量数量。
            filters: 可选的元数据过滤条件，用于缩小搜索结果范围。

        返回:
            字典列表，每个字典至少包含 'id' 和 'score' 键，
            可选包含 'metadata'。
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        清除存储中所有的向量和元数据。
        """
        pass
