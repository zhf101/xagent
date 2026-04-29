from abc import ABC, abstractmethod
from typing import List, Optional, Union


class BaseEmbedding(ABC):
    """嵌入模型的抽象基类。"""

    @abstractmethod
    def encode(
        self,
        text: Union[str, List[str]],
        dimension: Optional[int] = None,
        instruct: Optional[str] = None,
    ) -> Union[List[float], List[List[float]]]:
        """
        Encode text into embedding vector(s).

        Args:
            text: Single text string or list of text strings
            dimension: 覆盖默认嵌入维度
            instruct: 覆盖默认指令

        Returns:
            单个文本返回单个嵌入向量（浮点数列表），
            文本列表返回嵌入向量列表
        """
        pass

    @abstractmethod
    def get_dimension(self) -> Optional[int]:
        """Get the embedding dimension."""
        pass

    @property
    @abstractmethod
    def abilities(self) -> List[str]:
        """Get the list of abilities supported by this model."""
        pass
