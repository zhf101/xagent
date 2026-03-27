"""存量场景向量索引器。

在 catalog 同步后维护 LanceDB 向量表，
为 LegacyScenarioRetriever 的 ANN 粗召回提供数据源。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_legacy_scenario_vectors"


def _scenario_row_id(scenario_id: str) -> str:
    """将任意 scenario_id 映射为向量表行 id（sha8 前缀避免特殊字符问题）。"""
    h = hashlib.sha256(scenario_id.encode()).hexdigest()[:8]
    return f"scen_{h}"


def build_scenario_doc(entry: dict[str, Any]) -> str:
    """将存量场景字段拼成用于 embedding 的自然语言描述。

    拼接顺序：场景名 > 描述 > business_tags > entity_tags > 输入参数 > 风险/审批 > 服务/工具。
    """
    parts: list[str] = []

    scenario_name = (entry.get("scenario_name") or "").strip()
    if scenario_name:
        parts.append(scenario_name)

    description = (entry.get("description") or "").strip()
    if description:
        parts.append(description)

    business_tags = entry.get("business_tags") or []
    if business_tags:
        parts.append("业务标签：" + "、".join(str(t) for t in business_tags if t))

    entity_tags = entry.get("entity_tags") or []
    if entity_tags:
        parts.append("实体标签：" + "、".join(str(t) for t in entity_tags if t))

    input_schema_summary = entry.get("input_schema_summary") or []
    if input_schema_summary:
        parts.append("输入参数：" + "、".join(str(t) for t in input_schema_summary if t))

    system_short = (entry.get("system_short") or "").strip()
    if system_short:
        parts.append(f"系统：{system_short}")

    risk_level = (entry.get("risk_level") or "").strip()
    if risk_level:
        parts.append(f"风险：{risk_level}")

    approval_policy = (entry.get("approval_policy") or "").strip()
    if approval_policy:
        parts.append(f"审批：{approval_policy}")

    server_name = (entry.get("server_name") or "").strip()
    if server_name:
        parts.append(f"服务：{server_name}")

    tool_name = (entry.get("tool_name") or "").strip()
    if tool_name:
        parts.append(f"工具：{tool_name}")

    return " ".join(parts)


class LegacyScenarioIndexer:
    """维护存量场景向量索引的写入端。"""

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
                    "scenario_id": "",
                    "text": "sample",
                    "vector": sample_vec,
                }
            ]
        else:
            sample = [
                {
                    "id": "__init__",
                    "scenario_id": "",
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
            logger.warning("存量场景 embedding 生成失败，跳过向量索引", exc_info=True)
            return None

    def index(self, entry: dict[str, Any]) -> bool:
        """对单个存量场景建立/更新向量索引（upsert 语义）。

        entry 字段期望包含：scenario_id, scenario_name, description,
        business_tags, entity_tags, system_short

        返回 True 表示写入成功，False 表示 embedding 不可用或写入失败。
        """
        scenario_id = entry.get("scenario_id")
        if not scenario_id:
            return False

        doc = build_scenario_doc(entry)
        vector = self._get_embedding(doc)
        row_id = _scenario_row_id(scenario_id)

        record: dict[str, Any] = {
            "id": row_id,
            "scenario_id": scenario_id,
            "text": doc,
        }
        if vector:
            record["vector"] = vector

        try:
            table = self._get_table()
            table.delete(f"id = '{row_id}'")
            table.add([record])
            return True
        except Exception:
            logger.warning("存量场景 %s 向量索引写入失败", scenario_id, exc_info=True)
            return False

    def delete(self, scenario_id: str) -> bool:
        """删除单个存量场景的向量索引条目。"""
        row_id = _scenario_row_id(scenario_id)
        try:
            table = self._get_table()
            table.delete(f"id = '{row_id}'")
            return True
        except Exception:
            logger.warning("存量场景 %s 向量索引删除失败", scenario_id, exc_info=True)
            return False

    def index_all(self, entries: list[dict[str, Any]]) -> int:
        """批量重建全部存量场景的向量索引。

        返回成功写入的条目数。
        """
        success = 0
        for entry in entries:
            if self.index(entry):
                success += 1
        return success
