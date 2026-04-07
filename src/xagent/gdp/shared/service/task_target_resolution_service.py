"""为任务解析并持久化 SQL 目标选择。

这个模块的核心职责是回答一个非常实际的问题：

“当前这个任务，到底应该连哪个数据源、哪个知识库？”

在 SQL 相关功能里，一个用户通常不止一个数据源。如果没有任务级确认，
模型每次都只能靠问题文本临时猜测，容易出现：

- 同一任务前后命中不同数据源
- ask/query/execution 链路上下文不一致
- 用户明明已经选过一次，后面却还要重复选择

因此这里把 SQL 目标确认做成了一个任务级状态机：

1. 先看当前消息是否需要进入 SQL 目标确认流程
2. 如果用户已经确认过，就直接复用
3. 如果只有一个候选或候选明显胜出，则自动确认
4. 如果候选太多且无法判定，就返回一个前端可渲染的选择框描述
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from xagent.gdp.vanna.model.text2sql import Text2SQLDatabase
from xagent.gdp.vanna.model.vanna import VannaKnowledgeBase, VannaKnowledgeBaseStatus
from xagent.web.models.task import Task

logger = logging.getLogger(__name__)


class TaskTargetResolutionService:
    """解析并保存任务级 SQL 目标。"""

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
        """处理一条消息对应的 SQL 目标解析流程。

        可以把这个方法理解为“任务 SQL 目标确认的总入口”：

        - 输入：当前任务、用户、问题文本、以及可能存在的用户澄清回答
        - 输出：当前是否已经拿到 SQL 目标，还是需要继续向用户提问
        """
        question_text = str(question or "").strip()
        state = self._get_state(task)

        # 如果这次请求带着用户在选择框里的回答，就优先消费这次回答。
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

        # 一旦任务里已经确认过目标，后续同任务消息直接复用，避免重复确认。
        confirmed = state.get("confirmed")
        if isinstance(confirmed, dict):
            return {"status": "resolved", "resolved_target": confirmed}

        # 当前用户没有任何候选数据源/知识库时，本流程不适用。
        if not candidates:
            return {"status": "not_applicable", "resolved_target": None}

        # 问题看起来不像 SQL 场景时，不要强行打断用户去选目标。
        if not self._should_prompt_for_sql_target(question_text):
            return {"status": "not_applicable", "resolved_target": None}

        # 只有一个候选时，直接自动确认是最自然的体验。
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

        # 多候选时先做一次轻量排序，如果明显有第一名，就自动确认。
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

        # 实在分不出来时，再把候选项交给前端渲染成选择框。
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
        """读取任务已经确认过的 SQL 目标。

        这个方法主要给工具运行时调用。工具本身不关心目标是怎么确认出来的，
        只需要一个稳定的最终结果。
        """
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
        """根据问题文本判断是否像 SQL 场景。

        这里不是高精度分类器，只做一个简单、可解释的启发式判断，
        目的是挡掉明显不相关的普通对话。
        """
        normalized = str(question or "").strip().lower()
        if not normalized:
            return False
        return any(hint in normalized for hint in self._SQL_HINTS)

    def _list_candidates(self, *, owner_user_id: int) -> List[Dict[str, Any]]:
        """列出当前用户可供选择的“数据源 + 知识库”候选。

        这里返回的不是纯 datasource，也不是纯 knowledge base，而是二者组合。
        因为真实 SQL 链路里：

        - datasource 负责连库
        - knowledge base 负责检索增强
        """
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
        """按照问题文本给候选打一个简单相关性分数。

        这里故意不用复杂模型，只看 label、system_short、env、数据库名等词面重合。
        这样做的好处是逻辑透明，出了错也容易排查。
        """
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
        """把解析状态写回 task.agent_config。

        当前没有为“任务 SQL 目标确认”单独建表，而是把状态直接挂在任务配置里。
        原因是这份状态数据量很小，而且天然依附于 task。
        """
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
