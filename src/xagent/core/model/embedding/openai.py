from __future__ import annotations

from typing import Any, List, Optional, Union

import requests

from .base import BaseEmbedding


class OpenAIEmbedding(BaseEmbedding):
    """OpenAI 文本嵌入模型客户端。
    使用 OpenAI 嵌入 API 进行文本向量化。"""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: Optional[int] = None,
    ):
        """
        Initialize OpenAI embedding client.

        Args:
            model: 模型名称（默认：text-embedding-3-small）
            api_key: OpenAI API 密钥（或设置 OPENAI_API_KEY 环境变量）
            base_url: API 基础地址
            dimension: 可选的嵌入维度（用于支持此参数的模型）
        """
        self.model = model
        self.api_key = api_key

        # 确保 base_url 以 /embeddings 结尾，以兼容 OpenAI 兼容 API
        if base_url:
            # 先去掉尾部斜杠以进行一致检查
            clean_base_url = base_url.rstrip("/")

            # 如果 base_url 不以 /embeddings 结尾，则追加
            if not clean_base_url.endswith("/embeddings"):
                # 检查是否以 /v1 或类似路径结尾
                if clean_base_url.endswith("/v1"):
                    self.base_url = clean_base_url + "/embeddings"
                else:
                    # 其他情况保持原样（可能是自定义端点）
                    self.base_url = base_url
            else:
                # 已包含 /embeddings，使用清理后的版本
                self.base_url = clean_base_url
        else:
            self.base_url = "https://api.openai.com/v1/embeddings"

        self.dimension = dimension
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = requests.Session()
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session.headers.update(headers)
        return self._session

    def _requires_api_key(self) -> bool:
        return self.base_url == "https://api.openai.com/v1/embeddings"

    @staticmethod
    def _extract_error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("detail")
                if message:
                    return str(message)

            detail = payload.get("detail")
            if detail:
                return str(detail)

            message = payload.get("message")
            if message:
                return str(message)

        response_text = response.text.strip()
        if response_text:
            return response_text

        return f"HTTP {response.status_code} error"

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
            instruct: 对 OpenAI 嵌入无用

        Returns:
            单个文本返回单个嵌入向量（浮点数列表），
            文本列表返回嵌入向量列表

        Raises:
            RuntimeError: 如果 API 调用失败或返回无效响应
        """
        if self._requires_api_key() and not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required")

        session = self._get_session()

        # Handle single text vs batch
        if isinstance(text, str):
            texts = [text]
            single_input = True
        else:
            texts = text
            single_input = False

        # Prepare request payload
        payload: dict[str, Any] = {
            "model": self.model,
            "input": texts,
        }

        # Add dimension if provided
        final_dimension = dimension or self.dimension
        if final_dimension:
            payload["dimensions"] = final_dimension

        response: Optional[requests.Response] = None

        try:
            response = session.post(self.base_url or "", json=payload)
            response.raise_for_status()

            data = response.json()

            if "data" not in data:
                raise ValueError(f"Unexpected response format: {data}")

            embeddings = data["data"]

            # Extract embedding vectors
            if single_input:
                embedding: list[float] = embeddings[0]["embedding"]
                return embedding
            else:
                embedding_list: list[list[float]] = [
                    emb["embedding"] for emb in embeddings
                ]
                return embedding_list

        except requests.HTTPError as e:
            if response is None and e.response is not None:
                response = e.response

            if response is None:
                raise RuntimeError(f"OpenAI embedding failed: {str(e)}") from e

            detail = self._extract_error_detail(response)
            raise RuntimeError(f"OpenAI embedding failed: {detail}") from e
        except Exception as e:
            import traceback

            raise RuntimeError(
                f"OpenAI embedding failed: {str(e)}\n{traceback.format_exc()}"
            )

    def get_dimension(self) -> Optional[int]:
        """Get the embedding dimension."""
        return self.dimension

    @property
    def abilities(self) -> List[str]:
        """Get the list of abilities supported by this model."""
        return ["embed"]
