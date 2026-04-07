"""Task-scoped target resolution for Vanna SQL usage."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models.task import Task
from ..models.text2sql import Text2SQLDatabase
from ..models.vanna import VannaKnowledgeBase, VannaKnowledgeBaseStatus

logger = logging.getLogger(__name__)


class TaskTargetResolutionService:
    """Resolve and persist a task-scoped Vanna SQL target."""

    CONFIG_KEY = "vanna_target_resolution"
    FIELD_NAME = "vanna_target"
    _TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
    _SQL_HINTS = (
        "sql",
        "数据库",
        "数据源",
        "表",
        "字段",
        "schema",
        "ddl",
        "查询",
        "统计",
        "汇总",
        "分析",
        "count",
        "sum",
        "group by",
        "select",
        "where",
    )

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve_for_message(
        self,
        *,
        task: Task,
        owner_user_id: int,
        question: str,
        clarification_response: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        question_text = str(question or "").strip()
        state = self._get_state(task)

        selected_value = self._extract_selected_value(clarification_response)
        candidates = self._list_candidates(owner_user_id=owner_user_id)

        if selected_value:
            selected = self._find_candidate_by_value(candidates, selected_value)
            if selected is None:
                logger.warning(
                    "Task %s submitted unknown Vanna target option: %s",
                    getattr(task, "id", None),
                    selected_value,
                )
            else:
                confirmed_payload = self._to_confirmed_payload(selected)
                self._persist_state(
                    task,
                    {
                        "confirmed": confirmed_payload,
                        "pending_options": [],
                        "last_mode": "user_confirmed",
                    },
                )
                return {"status": "resolved", "resolved_target": confirmed_payload}

        confirmed = state.get("confirmed")
        if isinstance(confirmed, dict):
            return {"status": "resolved", "resolved_target": confirmed}

        if not candidates:
            return {"status": "not_applicable", "resolved_target": None}

        if not self._should_prompt_for_sql_target(question_text):
            return {"status": "not_applicable", "resolved_target": None}

        if len(candidates) == 1:
            selected = candidates[0]
            confirmed_payload = self._to_confirmed_payload(selected)
            self._persist_state(
                task,
                {
                    "confirmed": confirmed_payload,
                    "pending_options": [],
                    "last_mode": "auto_single_candidate",
                },
            )
            return {"status": "resolved", "resolved_target": confirmed_payload}

        ranked = self._rank_candidates(question=question_text, candidates=candidates)
        top_candidate = ranked[0]
        second_score = ranked[1]["score"] if len(ranked) > 1 else 0.0
        if top_candidate["score"] >= 1.2 and (
            second_score <= 0 or top_candidate["score"] - second_score >= 0.6
        ):
            confirmed_payload = self._to_confirmed_payload(top_candidate)
            self._persist_state(
                task,
                {
                    "confirmed": confirmed_payload,
                    "pending_options": [],
                    "last_mode": "auto_ranked_match",
                },
            )
            return {"status": "resolved", "resolved_target": confirmed_payload}

        options = [
            {
                "value": candidate["value"],
                "label": candidate["label"],
            }
            for candidate in ranked[:8]
        ]
        self._persist_state(
            task,
            {
                "confirmed": None,
                "pending_options": [
                    {
                        "value": option["value"],
                        "label": option["label"],
                    }
                    for option in options
                ],
                "last_mode": "awaiting_user_confirmation",
            },
        )
        return {
            "status": "needs_user_input",
            "message": "这次任务涉及 SQL 数据查询，请先确认本次要使用的 SQL 目标。",
            "interactions": [
                {
                    "type": "select_one",
                    "field": self.FIELD_NAME,
                    "label": "SQL 目标",
                    "options": options,
                    "placeholder": "请选择本次任务要使用的数据源 / 知识库",
                }
            ],
            "resolved_target": None,
        }

    def load_confirmed_target(
        self,
        *,
        task_id: int,
        owner_user_id: int,
    ) -> Optional[Dict[str, Any]]:
        task = (
            self.db.query(Task)
            .filter(Task.id == int(task_id), Task.user_id == int(owner_user_id))
            .first()
        )
        if task is None:
            return None
        state = self._get_state(task)
        confirmed = state.get("confirmed")
        return confirmed if isinstance(confirmed, dict) else None

    def _should_prompt_for_sql_target(self, question: str) -> bool:
        normalized = str(question or "").strip().lower()
        if not normalized:
            return False
        return any(hint in normalized for hint in self._SQL_HINTS)

    def _list_candidates(self, *, owner_user_id: int) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(VannaKnowledgeBase, Text2SQLDatabase)
            .join(
                Text2SQLDatabase,
                Text2SQLDatabase.id == VannaKnowledgeBase.datasource_id,
            )
            .filter(
                VannaKnowledgeBase.owner_user_id == int(owner_user_id),
                VannaKnowledgeBase.status == VannaKnowledgeBaseStatus.ACTIVE.value,
                Text2SQLDatabase.user_id == int(owner_user_id),
            )
            .order_by(VannaKnowledgeBase.id.asc())
            .all()
        )

        candidates: List[Dict[str, Any]] = []
        for kb, datasource in rows:
            label = " / ".join(
                [
                    str(part)
                    for part in [
                        getattr(kb, "system_short", None) or getattr(datasource, "system_short", None),
                        getattr(kb, "env", None) or getattr(datasource, "env", None),
                        getattr(datasource, "name", None),
                        getattr(kb, "name", None),
                    ]
                    if str(part or "").strip()
                ]
            )
            candidates.append(
                {
                    "value": f"kb:{int(kb.id)}|ds:{int(datasource.id)}",
                    "label": label or f"datasource {int(datasource.id)} / kb {int(kb.id)}",
                    "kb_id": int(kb.id),
                    "kb_name": str(getattr(kb, "name", "") or ""),
                    "datasource_id": int(datasource.id),
                    "datasource_name": str(getattr(datasource, "name", "") or ""),
                    "system_short": str(
                        getattr(kb, "system_short", None)
                        or getattr(datasource, "system_short", None)
                        or ""
                    ),
                    "env": str(
                        getattr(kb, "env", None) or getattr(datasource, "env", None) or ""
                    ),
                    "database_name": str(
                        getattr(kb, "database_name", None)
                        or getattr(datasource, "database_name", None)
                        or ""
                    ),
                }
            )
        return candidates

    def _rank_candidates(
        self,
        *,
        question: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized = str(question or "").strip().lower()
        question_tokens = self._tokenize(normalized)
        ranked: List[Dict[str, Any]] = []
        for candidate in candidates:
            score = 0.0
            fields = [
                str(candidate.get("label") or "").lower(),
                str(candidate.get("datasource_name") or "").lower(),
                str(candidate.get("kb_name") or "").lower(),
                str(candidate.get("system_short") or "").lower(),
                str(candidate.get("env") or "").lower(),
                str(candidate.get("database_name") or "").lower(),
            ]
            for field in fields:
                if not field:
                    continue
                if field in normalized:
                    score += 0.8
                field_tokens = self._tokenize(field)
                overlap = question_tokens.intersection(field_tokens)
                if overlap:
                    score += 0.25 * len(overlap)
            ranked.append({**candidate, "score": round(score, 4)})
        ranked.sort(
            key=lambda item: (float(item["score"]), int(item["datasource_id"])),
            reverse=True,
        )
        return ranked

    def _extract_selected_value(
        self,
        clarification_response: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if not isinstance(clarification_response, dict):
            return None
        answers = clarification_response.get("answers")
        if not isinstance(answers, dict):
            return None
        answer = answers.get(self.FIELD_NAME)
        if not isinstance(answer, dict):
            return None
        value = answer.get("value")
        return str(value).strip() if value is not None else None

    def _find_candidate_by_value(
        self, candidates: List[Dict[str, Any]], value: str
    ) -> Optional[Dict[str, Any]]:
        for candidate in candidates:
            if str(candidate.get("value")) == str(value):
                return candidate
        return None

    def _to_confirmed_payload(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "datasource_id": int(candidate["datasource_id"]),
            "datasource_name": str(candidate["datasource_name"]),
            "kb_id": int(candidate["kb_id"]),
            "kb_name": str(candidate["kb_name"]),
            "label": str(candidate["label"]),
            "value": str(candidate["value"]),
        }

    def _get_state(self, task: Task) -> Dict[str, Any]:
        config = (
            dict(task.agent_config)
            if isinstance(getattr(task, "agent_config", None), dict)
            else {}
        )
        state = config.get(self.CONFIG_KEY)
        return dict(state) if isinstance(state, dict) else {}

    def _persist_state(self, task: Task, state: Dict[str, Any]) -> None:
        config = (
            dict(task.agent_config)
            if isinstance(getattr(task, "agent_config", None), dict)
            else {}
        )
        config[self.CONFIG_KEY] = state
        task.agent_config = config
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

    def _tokenize(self, text: str) -> set[str]:
        return {
            token
            for token in self._TOKEN_PATTERN.findall(str(text or "").lower())
            if len(token) >= 2
        }
