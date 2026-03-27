"""HTTP 资产向量索引器。

在 HTTP 资产发布/更新/删除时维护 LanceDB 向量表，
为 HttpAssetRetriever 的 ANN 粗召回提供数据源。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_http_asset_vectors"


def build_http_asset_doc(asset: dict[str, Any]) -> str:
    """将 HTTP 资产结构化字段拼成用于 embedding 的自然语言描述。

    拼接顺序：名称 > 描述 > method + path > base_url > 鉴权 > 参数键信息 > 响应提取。
    """
    parts: list[str] = []

    name = (asset.get("name") or "").strip()
    if name:
        parts.append(name)

    description = (asset.get("description") or "").strip()
    if description:
        parts.append(description)

    config = asset.get("config") or {}
    method = (config.get("method") or "").strip().upper()
    path_template = (config.get("path_template") or "").strip()
    if method and path_template:
        parts.append(f"{method} {path_template}")
    elif path_template:
        parts.append(path_template)

    base_url = (config.get("base_url") or "").strip()
    if base_url:
        parts.append(base_url)

    auth_type = (config.get("auth_type") or "").strip()
    if auth_type:
        parts.append(f"鉴权：{auth_type}")

    for label, key in (
        ("Query 参数", "query_params"),
        ("请求头", "default_headers"),
        ("JSON 字段", "json_body"),
        ("Form 字段", "form_fields"),
    ):
        value = config.get(key) or {}
        if isinstance(value, dict) and value:
            keys = [str(item) for item in value.keys()][:20]
            parts.append(f"{label}：" + "、".join(keys))

    response_extract = config.get("response_extract") or {}
    if isinstance(response_extract, dict) and response_extract:
        fields = response_extract.get("fields") or {}
        if isinstance(fields, dict) and fields:
            parts.append("响应提取：" + "、".join(str(item) for item in list(fields.keys())[:20]))

    system_short = (asset.get("system_short") or "").strip()
    if system_short:
        parts.append(f"系统：{system_short}")

    return " ".join(parts)


class HttpAssetIndexer:
    """维护 HTTP 资产向量索引的写入端。"""

    def __init__(self, db_dir: str, embedding_model: Any):
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._conn: Any = None

    def _get_conn(self) -> Any:
        if self._conn is None:
            from xagent.providers.vector_store.lancedb import LanceDBConnectionManager
            self._conn = LanceDBConnectionManager().get_connection(self._db_dir)
        return self._conn

    def _get_table(self) -> Any:
        conn = self._get_conn()
        try:
            return conn.open_table(COLLECTION_NAME)
        except Exception:
            return self._create_table(conn)

    def _create_table(self, conn: Any) -> Any:
        sample_vec = self._get_embedding("sample")
        if sample_vec:
            sample = [
                {
                    "id": "__init__",
                    "asset_id": 0,
                    "system_short": "",
                    "text": "sample",
                    "vector": sample_vec,
                }
            ]
        else:
            sample = [
                {
                    "id": "__init__",
                    "asset_id": 0,
                    "system_short": "",
                    "text": "sample",
                }
            ]
        table = conn.create_table(COLLECTION_NAME, data=sample)
        table.delete("id = '__init__'")
        return table

    def _get_embedding(self, text: str) -> list[float] | None:
        if not self._embedding_model or not text.strip():
            return None
        try:
            result = self._embedding_model.encode(text)
            if isinstance(result, list) and result:
                if isinstance(result[0], (int, float)):
                    return result  # type: ignore[return-value]
                if isinstance(result[0], list):
                    return result[0]
            return None
        except Exception:
            logger.warning("HTTP 资产 embedding 生成失败，跳过向量索引", exc_info=True)
            return None

    def index(self, asset: dict[str, Any]) -> bool:
        """对单个 HTTP 资产建立/更新向量索引（upsert 语义）。

        asset 字段期望包含：id, name, system_short, description, config
        （config 内含 method, path_template, base_url）

        返回 True 表示写入成功，False 表示 embedding 不可用或写入失败。
        """
        asset_id = asset.get("id")
        if not asset_id:
            return False

        doc = build_http_asset_doc(asset)
        vector = self._get_embedding(doc)

        record: dict[str, Any] = {
            "id": f"http_{asset_id}",
            "asset_id": int(asset_id),
            "system_short": asset.get("system_short") or "",
            "text": doc,
        }
        if vector:
            record["vector"] = vector

        try:
            table = self._get_table()
            table.delete(f"id = 'http_{asset_id}'")
            table.add([record])
            return True
        except Exception:
            logger.warning("HTTP 资产 %s 向量索引写入失败", asset_id, exc_info=True)
            return False

    def delete(self, asset_id: int) -> bool:
        """删除单个 HTTP 资产的向量索引条目。"""
        try:
            table = self._get_table()
            table.delete(f"id = 'http_{asset_id}'")
            return True
        except Exception:
            logger.warning("HTTP 资产 %s 向量索引删除失败", asset_id, exc_info=True)
            return False
