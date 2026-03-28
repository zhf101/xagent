"""Template query service for datamakepool.

提供模板的查询、发布、下线和存量重建索引能力：
- 列出已发布模板（支持 system_short 过滤）
- 批量按 ID 获取模板详情
- 读取模板当前版本的 step_spec 快照
- 发布/下线模板（更新 status，触发索引回调）
- 全量重建向量索引
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class TemplateService:
    def __init__(self, db: Session):
        self._db = db

    def _deserialize_row(self, row: Any) -> dict[str, Any]:
        """将数据库行转为统一的模板字典格式。"""
        tags = row.get("tags")
        applicable_systems = row.get("applicable_systems")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        if isinstance(applicable_systems, str):
            try:
                applicable_systems = json.loads(applicable_systems)
            except Exception:
                applicable_systems = []
        return {
            "id": row["id"],
            "name": row["name"],
            "system_short": row.get("system_short"),
            "description": row.get("description"),
            "tags": tags or [],
            "applicable_systems": applicable_systems or [],
            "current_version": row.get("current_version") or 1,
            "status": row.get("status"),
        }

    def list_templates(self, system_short: str | None = None) -> list[dict[str, Any]]:
        """列出已发布模板。

        system_short 非空时在 SQL 层先过滤，避免全量加载后内存过滤。
        兼容 applicable_systems JSON 字段的跨系统模板。
        """
        inspector = inspect(self._db.bind)
        if "datamakepool_templates" not in inspector.get_table_names():
            return []

        if system_short:
            rows = self._db.execute(
                text(
                    """
                    SELECT id, name, system_short, description, tags,
                           applicable_systems, current_version, status
                    FROM datamakepool_templates
                    WHERE status = 'active'
                      AND (
                          system_short = :sys
                          OR applicable_systems LIKE :sys_like
                      )
                    ORDER BY id DESC
                    """
                ),
                {"sys": system_short, "sys_like": f'%"{system_short}"%'},
            ).mappings()
        else:
            rows = self._db.execute(
                text(
                    """
                    SELECT id, name, system_short, description, tags,
                           applicable_systems, current_version, status
                    FROM datamakepool_templates
                    WHERE status = 'active'
                    ORDER BY id DESC
                    """
                )
            ).mappings()

        return [self._deserialize_row(row) for row in rows]

    def batch_get(self, ids: list[int]) -> list[dict[str, Any]]:
        """按 ID 列表批量获取模板详情（一次 IN 查询）。

        用于向量召回后批量加载候选模板的完整字段，供精排使用。
        顺序不保证与 ids 一致，由调用方自行处理。
        """
        if not ids:
            return []

        inspector = inspect(self._db.bind)
        if "datamakepool_templates" not in inspector.get_table_names():
            return []

        placeholders = ", ".join(str(i) for i in ids)
        rows = self._db.execute(
            text(
                f"""
                SELECT id, name, system_short, description, tags,
                       applicable_systems, current_version, status
                FROM datamakepool_templates
                WHERE id IN ({placeholders})
                  AND status = 'active'
                """
            )
        ).mappings()
        return [self._deserialize_row(row) for row in rows]

    def publish_template(
        self,
        template_id: int,
        on_indexed: Callable[[dict[str, Any]], None] | None = None,
    ) -> bool:
        """将模板状态改为 active，并触发向量索引回调。

        on_indexed 是可选回调，由调用方注入 TemplateIndexer.index，
        避免 service 层直接依赖 indexer（保持单向依赖）。
        """
        inspector = inspect(self._db.bind)
        if "datamakepool_templates" not in inspector.get_table_names():
            return False

        self._db.execute(
            text(
                "UPDATE datamakepool_templates SET status = 'active' WHERE id = :id"
            ),
            {"id": template_id},
        )
        self._db.commit()

        if on_indexed:
            spec = self.get_template_execution_spec(template_id)
            if spec:
                try:
                    on_indexed(spec)
                except Exception:
                    logger.warning(
                        "模板向量索引写入失败，模板已发布但索引未建立",
                        exc_info=True,
                    )
        return True

    def unpublish_template(
        self,
        template_id: int,
        on_deleted: Callable[[int], None] | None = None,
    ) -> bool:
        """将模板状态改为 disabled，并触发向量索引删除回调。"""
        inspector = inspect(self._db.bind)
        if "datamakepool_templates" not in inspector.get_table_names():
            return False

        self._db.execute(
            text(
                "UPDATE datamakepool_templates SET status = 'disabled' WHERE id = :id"
            ),
            {"id": template_id},
        )
        self._db.commit()

        if on_deleted:
            try:
                on_deleted(template_id)
            except Exception:
                logger.warning("模板向量索引删除失败", exc_info=True)
        return True

    def reindex_all(
        self,
        on_indexed: Callable[[dict[str, Any]], None],
    ) -> int:
        """对所有 active 模板触发向量索引重建，返回处理数量。

        用于存量数据补齐，或 embedding 模型切换后全量重建。
        """
        templates = self.list_templates()
        count = 0
        for tmpl in templates:
            spec = self.get_template_execution_spec(tmpl["id"])
            if spec:
                try:
                    on_indexed(spec)
                    count += 1
                except Exception:
                    logger.warning(
                        "模板 %s 重建索引失败", tmpl["id"], exc_info=True
                    )
        return count

    def get_template_execution_spec(
        self,
        template_id: int,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        inspector = inspect(self._db.bind)
        tables = set(inspector.get_table_names())
        if (
            "datamakepool_templates" not in tables
            or "datamakepool_template_versions" not in tables
        ):
            return None

        version_to_use = int(version) if version is not None else None
        row = self._db.execute(
            text(
                """
                SELECT t.id, t.name, t.system_short, t.current_version,
                       v.step_spec_snapshot
                FROM datamakepool_templates t
                LEFT JOIN datamakepool_template_versions v
                  ON v.template_id = t.id
                 AND v.version = COALESCE(:version, t.current_version)
                WHERE t.id = :template_id
                """
            ),
            {
                "template_id": template_id,
                "version": version_to_use,
            },
        ).mappings().first()

        if not row:
            return None

        step_spec = row.get("step_spec_snapshot")
        if isinstance(step_spec, str):
            try:
                step_spec = json.loads(step_spec)
            except Exception:
                step_spec = []

        return {
            "id": row["id"],
            "name": row["name"],
            "system_short": row.get("system_short"),
            "version": version_to_use or row.get("current_version") or 1,
            "step_spec": step_spec or [],
        }
