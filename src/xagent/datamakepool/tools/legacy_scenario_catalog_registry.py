"""Persistence-backed registry for historical scenario catalog entries."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from time import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from xagent.web.models.legacy_scenario_catalog import LegacyScenarioCatalog

CATALOG_STALE_SECONDS = 300


class LegacyScenarioCatalogRegistry:
    def __init__(self, db: Session, user_id: int):
        self._db = db
        self._user_id = user_id

    def _base_query(self):
        return self._db.query(LegacyScenarioCatalog).filter(
            LegacyScenarioCatalog.user_id == self._user_id,
            LegacyScenarioCatalog.catalog_type == "legacy_scenario",
        )

    def list_entries(self) -> list[LegacyScenarioCatalog]:
        return self._base_query().order_by(LegacyScenarioCatalog.updated_at.desc()).all()

    def get_entry(self, scenario_id: str) -> Optional[LegacyScenarioCatalog]:
        return (
            self._base_query()
            .filter(LegacyScenarioCatalog.scenario_id == scenario_id)
            .first()
        )

    def is_stale(self) -> bool:
        latest = (
            self._base_query()
            .order_by(LegacyScenarioCatalog.last_synced_at.desc())
            .first()
        )
        if latest is None or latest.last_synced_at is None:
            return True
        return (time() - latest.last_synced_at.timestamp()) > CATALOG_STALE_SECONDS

    def upsert_entries(self, entries: list[dict[str, Any]]) -> None:
        by_scenario = {entry["scenario_id"]: entry for entry in entries}
        existing_rows = {
            row.scenario_id: row
            for row in self._base_query()
            .filter(LegacyScenarioCatalog.scenario_id.in_(list(by_scenario.keys())))
            .all()
        }

        for scenario_id, entry in by_scenario.items():
            row = existing_rows.get(scenario_id)
            if row is None:
                row = LegacyScenarioCatalog(
                    user_id=self._user_id,
                    catalog_type="legacy_scenario",
                    scenario_id=scenario_id,
                )
                self._db.add(row)

            row.scenario_name = str(entry["scenario_name"])
            row.server_name = str(entry["server_name"])
            row.tool_name = str(entry["tool_name"])
            row.tool_load_ref = str(entry["tool_load_ref"])
            row.description = str(entry.get("description") or "")
            row.system_short = entry.get("system_short")
            row.business_tags = entry.get("business_tags") or []
            row.entity_tags = entry.get("entity_tags") or []
            row.input_schema_summary = entry.get("input_schema_summary") or []
            row.status = str(entry.get("status") or "active")
            row.approval_policy = entry.get("approval_policy")
            row.risk_level = entry.get("risk_level")
            row.usage_count = int(entry.get("usage_count") or row.usage_count or 0)
            row.success_count = int(
                entry.get("success_count") or row.success_count or 0
            )
            row.success_rate = int(
                entry.get("success_rate") or row.success_rate or 0
            )
            row.last_used_at = entry.get("last_used_at") or row.last_used_at
            row.last_synced_at = entry["last_synced_at"]

        self._db.commit()

    def search(self, query: str, system_short: Optional[str] = None, top_k: int = 6) -> list[dict[str, Any]]:
        query_lower = query.lower()
        rows = self.list_entries()
        scored: list[tuple[float, LegacyScenarioCatalog]] = []
        for row in rows:
            score = 0.0
            if system_short and row.system_short == system_short.lower():
                score += 0.45
            if row.system_short and row.system_short in query_lower:
                score += 0.25
            if row.scenario_name and row.scenario_name.lower() in query_lower:
                score += 0.35
            for token in re.split(r"\s+|，|,|；|;", query_lower):
                if not token:
                    continue
                if row.scenario_name and token in row.scenario_name.lower():
                    score += 0.12
            if row.description and token in row.description.lower():
                score += 0.08
            score += min((row.usage_count or 0) * 0.015, 0.2)
            score += min((row.success_rate or 0) / 1000.0, 0.1)
            if row.last_used_at is not None:
                days_since_use = max(
                    0.0,
                    (datetime.now(timezone.utc) - row.last_used_at.replace(tzinfo=timezone.utc if row.last_used_at.tzinfo is None else row.last_used_at.tzinfo)).days,
                )
                score += max(0.0, 0.08 - min(days_since_use, 30) * 0.002)
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "scenario_id": row.scenario_id,
                "scenario_name": row.scenario_name,
                "server_name": row.server_name,
                "tool_name": row.tool_name,
                "tool_load_ref": row.tool_load_ref,
                "description": row.description,
                "system_short": row.system_short,
                "business_tags": row.business_tags or [],
                "entity_tags": row.entity_tags or [],
                "input_schema_summary": row.input_schema_summary or [],
                "status": row.status,
                "approval_policy": row.approval_policy,
                "risk_level": row.risk_level,
                "usage_count": row.usage_count or 0,
                "success_rate": row.success_rate or 0,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "match_score": round(score, 4),
            }
            for score, row in scored[: max(1, min(top_k, 10))]
        ]

    def record_execution(self, scenario_id: str, success: bool) -> None:
        row = self.get_entry(scenario_id)
        if row is None:
            return
        row.usage_count = int(row.usage_count or 0) + 1
        if success:
            row.success_count = int(row.success_count or 0) + 1
        usage_count = max(int(row.usage_count or 0), 1)
        row.success_rate = int(round((int(row.success_count or 0) / usage_count) * 100))
        row.last_used_at = datetime.now(timezone.utc)
        self._db.commit()


def record_legacy_scenario_execution(user_id: int, scenario_id: str, success: bool) -> None:
    from xagent.web.models.database import get_session_local

    session_local = get_session_local()
    db = session_local()
    try:
        LegacyScenarioCatalogRegistry(db, user_id).record_execution(scenario_id, success)
    finally:
        db.close()
