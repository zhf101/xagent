"""Template query service for datamakepool.

当前版本只提供最小能力：
- 列出已发布模板
- 读取模板当前版本的 step_spec 快照
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


class TemplateService:
    def __init__(self, db: Session):
        self._db = db

    def list_templates(self) -> list[dict[str, Any]]:
        inspector = inspect(self._db.bind)
        if "datamakepool_templates" not in inspector.get_table_names():
            return []

        rows = self._db.execute(
            text(
                """
                SELECT id, name, system_short, tags, applicable_systems, current_version, status
                FROM datamakepool_templates
                WHERE status = 'published'
                ORDER BY id DESC
                """
            )
        ).mappings()

        results: list[dict[str, Any]] = []
        for row in rows:
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

            results.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "system_short": row.get("system_short"),
                    "tags": tags or [],
                    "applicable_systems": applicable_systems or [],
                    "current_version": row.get("current_version") or 1,
                }
            )
        return results

    def get_template_execution_spec(self, template_id: int) -> dict[str, Any] | None:
        inspector = inspect(self._db.bind)
        tables = set(inspector.get_table_names())
        if (
            "datamakepool_templates" not in tables
            or "datamakepool_template_versions" not in tables
        ):
            return None

        row = self._db.execute(
            text(
                """
                SELECT t.id, t.name, t.system_short, t.current_version,
                       v.step_spec_snapshot
                FROM datamakepool_templates t
                LEFT JOIN datamakepool_template_versions v
                  ON v.template_id = t.id AND v.version = t.current_version
                WHERE t.id = :template_id
                """
            ),
            {"template_id": template_id},
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
            "version": row.get("current_version") or 1,
            "step_spec": step_spec or [],
        }
