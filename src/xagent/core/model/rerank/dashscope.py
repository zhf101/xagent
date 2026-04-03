# import os
# from collections.abc import Sequence
# from typing import Any, Optional
#
# import requests
#
# from .base import BaseRerank
#
# OLD_FORMAT_MODELS = {"gte-rerank-v2"}
#
#
# class DashscopeRerank(BaseRerank):
#     """DashScope rerank client kept for backward compatibility."""
#
#     def __init__(
#         self,
#         model: str = "qwen3-rerank",
#         api_key: Optional[str] = None,
#         base_url: Optional[str] = None,
#         top_n: Optional[int] = None,
#         instruct: Optional[str] = None,
#     ):
#         self.model = model
#         self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
#         self.top_n = top_n
#         self.instruct = instruct
#         self.url = (
#             base_url
#             or "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
#         )
#
#         if not self.api_key:
#             raise ValueError("API key required")
#
#     def compress(
#         self,
#         documents: Sequence[str],
#         query: str,
#     ) -> Sequence[str]:
#         headers = {
#             "Authorization": f"Bearer {self.api_key}",
#             "Content-Type": "application/json",
#         }
#
#         documents = list(documents)
#         is_new_format = self.model.lower() not in OLD_FORMAT_MODELS
#
#         optional_params: dict[str, Any] = {}
#         if self.top_n is not None:
#             optional_params["top_n"] = self.top_n
#         if self.instruct is not None:
#             optional_params["instruct"] = self.instruct
#
#         if is_new_format:
#             payload = {
#                 "model": self.model,
#                 "query": query,
#                 "documents": documents,
#             } | optional_params
#         else:
#             payload = {
#                 "model": self.model,
#                 "input": {
#                     "query": query,
#                     "documents": documents,
#                 },
#                 "parameters": {"return_documents": True} | optional_params,
#             }
#
#         response = requests.post(self.url, headers=headers, json=payload)
#         response.raise_for_status()
#         data = response.json()
#
#         if is_new_format:
#             results = data["results"]
#             return [documents[int(result["index"])] for result in results]
#
#         results = data["output"]["results"]
#         return [result["document"]["text"] for result in results]
