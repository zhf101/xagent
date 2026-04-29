from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .core import MemoryNote, MemoryResponse


class MemoryStore(ABC):
    """
    记忆存储后端的抽象基类，定义统一的存储接口。

    任何具体实现（例如纯内存存储、LanceDB、Redis 等）
    都需要实现以下所有方法，以管理 MemoryNote 对象。
    """

    @abstractmethod
    def add(self, note: "MemoryNote") -> "MemoryResponse":
        """
        将一条记忆添加到存储中。

        参数:
            note (MemoryNote): 待添加的记忆记录。

        返回:
            MemoryResponse: 包含操作是否成功及记忆 ID 的响应。
        """
        pass

    @abstractmethod
    def get(self, note_id: str) -> "MemoryResponse":
        """
        根据 ID 检索一条记忆。

        参数:
            note_id (str): 记忆的唯一标识符。

        返回:
            MemoryResponse: 包含记忆内容或错误信息的响应。
        """
        pass

    @abstractmethod
    def update(self, note: "MemoryNote") -> "MemoryResponse":
        """
        更新一条已有的记忆记录。

        参数:
            note (MemoryNote): 包含更新后数据的记忆记录。

        返回:
            MemoryResponse: 表示操作成功或失败的响应。
        """
        pass

    @abstractmethod
    def delete(self, note_id: str) -> "MemoryResponse":
        """
        根据 ID 删除一条记忆。

        参数:
            note_id (str): 记忆的唯一标识符。

        返回:
            MemoryResponse: 表示操作成功或失败的响应。
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
        按查询文本搜索记忆，支持可选过滤条件。

        参数:
            query (str): 用于搜索的查询字符串。
            k (int, 可选): 返回的最大结果数，默认为 5。
            filters (Dict[str, Any], 可选): 额外的过滤条件，默认为 None。

        返回:
            List[MemoryNote]: 匹配的记忆列表。
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        清空存储中的所有记忆。
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
        列出所有记忆，支持可选过滤和分页。

        参数:
            filters (Dict[str, Any], 可选): 过滤条件，如分类、日期范围等。
            limit (int, 可选): 返回记录的最大数量。``None`` 表示不限制。
            offset (int, 可选): 跳过的匹配记录数，默认为 0。

        返回:
            List[MemoryNote]: 匹配过滤条件的记忆列表。
        """
        pass

    @abstractmethod
    def count(self, filters: Optional[dict[str, Any]] = None) -> int:
        """
        统计匹配可选过滤条件的记忆数量。

        参数:
            filters (Dict[str, Any], 可选): 过滤条件，如分类、日期范围等。

        返回:
            int: 匹配过滤条件的记忆数量。
        """
        pass

    @abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """
        获取记忆存储的统计信息。

        返回:
            Dict[str, Any]: 统计信息，包括总数、按分类计数等。
        """
        pass
