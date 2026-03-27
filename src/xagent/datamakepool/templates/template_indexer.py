"""模板向量索引器。

负责在模板发布/下线时维护 LanceDB 向量表 `datamakepool_template_vectors`，
为 TemplateRetriever 的 ANN 召回提供数据源。

设计原则：
- 表不存在时自动建表，不需要迁移脚本
- embedding 不可用时静默跳过，不阻塞模板发布主流程
- 支持单条 upsert 和全量重建两种写入模式
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "datamakepool_template_vectors"


def build_template_doc(template: dict[str, Any]) -> str:
    """将模板结构化字段拼成一段用于 embedding 的自然语言描述。

    拼接顺序：名称 > 描述 > 标签 > 适用系统 > 步骤名称。
    这样 embedding 向量能同时覆盖模板的业务语义和执行步骤语义。
    """
    parts: list[str] = []

    name = (template.get("name") or "").strip()
    if name:
        parts.append(name)

    description = (template.get("description") or "").strip()
    if description:
        parts.append(description)

    tags = template.get("tags") or []
    if tags:
        parts.append("标签：" + "、".join(str(t) for t in tags if t))

    system_short = (template.get("system_short") or "").strip()
    if system_short:
        parts.append(f"适用系统：{system_short}")

    applicable_systems = template.get("applicable_systems") or []
    if applicable_systems:
        parts.append("兼容系统：" + "、".join(str(s) for s in applicable_systems if s))

    step_spec = template.get("step_spec") or []
    step_names = [s.get("name", "") for s in step_spec if isinstance(s, dict) and s.get("name")]
    if step_names:
        parts.append("执行步骤：" + "、".join(step_names))

    return " ".join(parts)


class TemplateIndexer:
    """维护模板向量索引的写入端。"""

    def __init__(self, db_dir: str, embedding_model: Any):
        """
        Args:
            db_dir: LanceDB 数据目录，与项目其他 LanceDB 用法保持一致。
            embedding_model: BaseEmbedding 实例，调用 encode() 方法。
        """
        self._db_dir = db_dir
        self._embedding_model = embedding_model
        self._conn: Any = None

    def _get_conn(self) -> Any:
        """懒加载 LanceDB 连接，复用连接管理器的缓存机制。"""
        if self._conn is None:
            from xagent.providers.vector_store.lancedb import LanceDBConnectionManager
            self._conn = LanceDBConnectionManager().get_connection(self._db_dir)
        return self._conn

    def _get_table(self) -> Any:
        """获取向量表，不存在时自动建表。"""
        conn = self._get_conn()
        try:
            return conn.open_table(COLLECTION_NAME)
        except Exception:
            return self._create_table(conn)

    def _create_table(self, conn: Any) -> Any:
        """使用一条占位记录建表，建完后删除占位行。"""
        sample_vec = self._get_embedding("sample")
        if sample_vec:
            sample = [
                {
                    "id": "__init__",
                    "template_id": 0,
                    "system_short": "",
                    "text": "sample",
                    "vector": sample_vec,
                }
            ]
        else:
            sample = [
                {
                    "id": "__init__",
                    "template_id": 0,
                    "system_short": "",
                    "text": "sample",
                }
            ]
        table = conn.create_table(COLLECTION_NAME, data=sample)
        table.delete("id = '__init__'")
        return table

    def _get_embedding(self, text: str) -> list[float] | None:
        """调用 embedding 模型，失败时返回 None 而不是抛异常。"""
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
            logger.warning("embedding 生成失败，跳过向量索引", exc_info=True)
            return None

    def index(self, template: dict[str, Any]) -> bool:
        """对单个模板建立/更新向量索引（upsert 语义）。

        模板字段期望包含 get_template_execution_spec() 的返回结构：
        id, name, system_short, description, tags, applicable_systems, step_spec

        返回 True 表示写入成功，False 表示 embedding 不可用或写入失败（不影响模板发布）。
        """
        template_id = template.get("id")
        if not template_id:
            return False

        doc = build_template_doc(template)
        vector = self._get_embedding(doc)

        record: dict[str, Any] = {
            "id": f"template_{template_id}",
            "template_id": int(template_id),
            "system_short": template.get("system_short") or "",
            "text": doc,
        }
        if vector:
            record["vector"] = vector

        try:
            table = self._get_table()
            # upsert：先删旧记录再插入
            table.delete(f"id = 'template_{template_id}'")
            table.add([record])
            return True
        except Exception:
            logger.warning("模板 %s 向量索引写入失败", template_id, exc_info=True)
            return False

    def delete(self, template_id: int) -> bool:
        """删除单个模板的向量索引条目。"""
        try:
            table = self._get_table()
            table.delete(f"id = 'template_{template_id}'")
            return True
        except Exception:
            logger.warning("模板 %s 向量索引删除失败", template_id, exc_info=True)
            return False
