"""HTTP 资产向量仓储。

这个仓储层的职责刻意保持很薄：
- 不参与权限判断
- 不参与规则排序
- 不把业务数据库字段原样复制一遍

它只负责把 HTTP 资产规整成统一 provider 可检索的向量文本，
以及把 provider 结果翻译回 `resource_id`。
"""

from __future__ import annotations

from typing import Any, Callable

from xagent.core.model.embedding.base import BaseEmbedding
from xagent.gdp.hrun.model.http_resource import GdpHttpResource
from xagent.providers.vector_store import VectorStore, create_vector_store
from xagent.web.services.model_service import (
    get_default_embedding_model,
    get_embedding_model,
)


def resolve_http_resource_embedding_runtime() -> tuple[BaseEmbedding | None, str | None]:
    """解析 HTTP 资产统一使用的 embedding 运行时。

    HTTP 资产是跨用户共享能力，不像 Vanna 那样天然绑定某个 KB。
    因此这里故意不按当前用户解析，而是统一使用系统默认 embedding，
    避免共享资产被不同用户的默认模型切成多套不兼容索引。
    """
    return get_embedding_model(None), get_default_embedding_model(None)


class HttpResourceVectorRepository:
    """HTTP 资产 provider 仓储。"""

    COLLECTION_NAME = "http_resource_global"

    def __init__(
        self,
        *,
        embedding_model: BaseEmbedding | None = None,
        embedding_model_name: str | None = None,
        vector_store_factory: Callable[..., VectorStore] = create_vector_store,
    ) -> None:
        self.embedding_model = embedding_model
        self.embedding_model_name = embedding_model_name
        self.vector_store_factory = vector_store_factory

    def upsert_resource(self, resource: GdpHttpResource) -> None:
        """写入或覆盖单个 HTTP 资产向量记录。"""
        vector = self._encode_query(self._build_embedding_text(resource))
        if not vector:
            return

        store = self.vector_store_factory(collection_name=self.COLLECTION_NAME)
        vector_id = self._vector_id(int(resource.id))
        store.delete_vectors([vector_id])
        store.add_vectors(
            vectors=[vector],
            ids=[vector_id],
            metadatas=[self._metadata_from_resource(resource)],
        )

    def delete_resource(self, resource_id: int) -> None:
        """删除单个 HTTP 资产向量记录。"""
        store = self.vector_store_factory(collection_name=self.COLLECTION_NAME)
        if not store.delete_vectors([self._vector_id(resource_id)]):
            raise RuntimeError(
                f"Failed to delete HTTP resource vector for resource_id={resource_id}"
            )

    def search_resources(
        self,
        *,
        query: str,
        top_k: int,
        system_short: str | None = None,
    ) -> list[dict[str, Any]]:
        """按查询文本召回候选资源。"""
        query_vector = self._encode_query(str(query or "").strip())
        if not query_vector:
            return []

        filters: dict[str, Any] = {"domain": "http_resource", "status": 1}
        if system_short:
            filters["system_short"] = str(system_short)

        hits = self.vector_store_factory(collection_name=self.COLLECTION_NAME).search_vectors(
            query_vector=query_vector,
            top_k=max(int(top_k), 1),
            filters=filters,
        )

        normalized_hits: list[dict[str, Any]] = []
        max_rank = max(len(hits), 1)
        for rank, hit in enumerate(hits, start=1):
            metadata = dict(hit.get("metadata") or {})
            resource_id = metadata.get("resource_id")
            if resource_id is None:
                continue
            normalized_hits.append(
                {
                    "resource_id": int(resource_id),
                    "provider_score": float(hit.get("score") or 0.0),
                    "rank_score": round((max_rank - rank + 1) / max_rank, 6),
                }
            )
        return normalized_hits

    def _encode_query(self, text: str) -> list[float] | None:
        if self.embedding_model is None or not text.strip():
            return None
        raw = self.embedding_model.encode(text)
        if not isinstance(raw, list):
            return None
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        vector = [float(item) for item in raw]
        return vector or None

    def _vector_id(self, resource_id: int) -> str:
        return f"http_resource_{int(resource_id)}"

    def _metadata_from_resource(self, resource: GdpHttpResource) -> dict[str, Any]:
        return {
            "domain": "http_resource",
            "resource_id": int(resource.id),
            "resource_key": resource.resource_key,
            "system_short": resource.system_short,
            "create_user_id": int(resource.create_user_id),
            "visibility": resource.visibility,
            "status": int(resource.status),
            "method": str(resource.method or "").upper(),
            "tool_name": resource.tool_name,
            "embedding_model": self.embedding_model_name,
            "text": self._build_embedding_text(resource),
        }

    def _build_embedding_text(self, resource: GdpHttpResource) -> str:
        """把 HTTP 资产收敛成用于 embedding 的文本。

        这里故意把“模型真正拿来判断是否调用此接口”的字段都拼进去，
        包括工具描述、参数 schema、请求模板、响应模板。
        这样像“自定义 body 模板”“返回值覆写策略”这类运行时配置，
        也能参与语义召回，而不是只能靠名字硬匹配。
        """
        parts = [
            resource.resource_key,
            resource.system_short,
            str(resource.method or "").upper(),
            resource.tool_name,
            resource.tool_description,
            resource.summary or "",
            " ".join(str(tag) for tag in (resource.tags_json or [])),
            self._collect_schema_text(resource.annotations_json or {}),
            self._collect_schema_text(resource.input_schema_json or {}),
            self._collect_schema_text(resource.output_schema_json or {}),
            self._collect_schema_text(resource.request_template_json or {}),
            self._collect_schema_text(resource.response_template_json or {}),
        ]
        return "\n".join(part for part in parts if str(part).strip()).strip()

    def _collect_schema_text(self, payload: Any) -> str:
        fragments: list[str] = []

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    fragments.append(str(child_key))
                    _walk(child_value)
            elif isinstance(value, list):
                for child in value:
                    _walk(child)
            elif isinstance(value, str):
                fragments.append(value)

        _walk(payload)
        return " ".join(fragments)
