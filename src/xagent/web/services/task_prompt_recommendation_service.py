from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, Iterable, List

from sqlalchemy.orm import Session

from ...core.memory.core import MemoryNote
from ..dynamic_memory_store import get_memory_store
from ..models.chat_message import TaskChatMessage
from ..models.task import Task
from ..models.task_prompt_recommendation import TaskPromptRecommendation
from ..user_isolated_memory import UserContext

SUPPORTED_MODES = ("data_generation", "data_consultation", "general")
PROFILE_STALE_AFTER = timedelta(hours=12)


THEME_LIBRARY: dict[str, list[dict[str, Any]]] = {
    "data_generation": [
        {
            "title": "生成一批用户订单测试数据",
            "description": "订单，用户，商品",
            "prompt": "生成一批用户订单测试数据",
            "keywords": ["订单", "order", "用户", "商品", "crm", "oms"],
        },
        {
            "title": "生成按时间分布的交易流水",
            "description": "时间序列，交易明细",
            "prompt": "生成按时间分布的交易流水",
            "keywords": ["交易", "流水", "支付", "账单", "transaction"],
        },
        {
            "title": "生成异常场景测试样本",
            "description": "边界值，异常数据",
            "prompt": "生成异常场景测试样本",
            "keywords": ["异常", "边界", "风控", "失败", "错误", "edge"],
        },
        {
            "title": "生成多表关联演示数据",
            "description": "主从表，关联关系",
            "prompt": "生成多表关联演示数据",
            "keywords": ["多表", "关联", "join", "主从", "schema"],
        },
    ],
    "data_consultation": [
        {
            "title": "某个造数模板应该怎么用",
            "description": "模板说明，参数解释",
            "prompt": "某个造数模板应该怎么用",
            "keywords": ["模板", "template", "参数", "怎么用", "使用"],
        },
        {
            "title": "这个场景该选哪类资产",
            "description": "资产选择，执行策略",
            "prompt": "这个场景该选哪类资产",
            "keywords": ["资产", "asset", "选择", "场景", "接口", "sql"],
        },
        {
            "title": "SQL 资产和 HTTP 资产有什么区别",
            "description": "资产类型，对比说明",
            "prompt": "SQL 资产和 HTTP 资产有什么区别",
            "keywords": ["区别", "对比", "sql", "http", "dubbo"],
        },
        {
            "title": "这次执行失败可能是什么原因",
            "description": "失败分析，排查建议",
            "prompt": "这次执行失败可能是什么原因",
            "keywords": ["失败", "报错", "error", "原因", "排查"],
        },
    ],
    "general": [
        {
            "title": "根据报告生成一个 PPT",
            "description": "销售报告，幻灯片",
            "prompt": "根据报告生成一个 PPT",
            "keywords": ["ppt", "汇报", "幻灯片", "报告"],
        },
        {
            "title": "分析数据集",
            "description": "趋势，反馈",
            "prompt": "分析数据集",
            "keywords": ["分析", "dataset", "图表", "趋势", "报表"],
        },
        {
            "title": "设计一张营销海报",
            "description": "社交媒体素材",
            "prompt": "设计一张营销海报",
            "keywords": ["海报", "设计", "营销", "poster", "banner"],
        },
        {
            "title": "自动化一个工作流程",
            "description": "自定义工作流",
            "prompt": "自动化一个工作流程",
            "keywords": ["自动化", "流程", "workflow", "脚本", "任务"],
        },
    ],
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate_title(value: str, limit: int = 28) -> str:
    clean = _normalize_text(value)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _safe_mode(task: Task) -> str:
    config = task.agent_config if isinstance(task.agent_config, dict) else {}
    mode = config.get("domain_mode")
    if isinstance(mode, str) and mode in SUPPORTED_MODES:
        return mode
    return "general"


def _extract_recent_task_texts(db: Session, user_id: int) -> dict[str, list[str]]:
    tasks = (
        db.query(Task)
        .filter(Task.user_id == user_id)
        .order_by(Task.created_at.desc())
        .limit(80)
        .all()
    )

    task_ids = [int(task.id) for task in tasks]
    first_messages: dict[int, str] = {}
    if task_ids:
        messages = (
            db.query(TaskChatMessage)
            .filter(
                TaskChatMessage.user_id == user_id,
                TaskChatMessage.task_id.in_(task_ids),
                TaskChatMessage.role == "user",
            )
            .order_by(TaskChatMessage.task_id.asc(), TaskChatMessage.created_at.asc())
            .all()
        )
        for message in messages:
            task_id = int(message.task_id)
            if task_id not in first_messages:
                first_messages[task_id] = str(message.content)

    texts: dict[str, list[str]] = {mode: [] for mode in SUPPORTED_MODES}
    for task in tasks:
        mode = _safe_mode(task)
        for candidate in [task.title, first_messages.get(int(task.id)), task.description]:
            if isinstance(candidate, str):
                clean = _normalize_text(candidate)
                if clean:
                    texts[mode].append(clean)

    return texts


def _extract_memory_texts(user_id: int) -> list[str]:
    try:
        with UserContext(user_id):
            memories = get_memory_store().list_all()
    except Exception:
        return []

    results: list[str] = []
    for memory in memories[:100]:
        if isinstance(memory, MemoryNote):
            clean = _normalize_text(memory.content)
            if clean:
                results.append(clean)
    return results


def _build_task_examples(mode: str, task_texts: Iterable[str]) -> list[dict[str, str]]:
    counter: Counter[str] = Counter()
    for text in task_texts:
        clean = _normalize_text(text)
        if len(clean) >= 6:
            counter[clean] += 1

    suffix = {
        "data_generation": "来自你的高频造数请求",
        "data_consultation": "来自你的高频问答问题",
        "general": "来自你的高频通用请求",
    }[mode]

    examples: list[dict[str, str]] = []
    for text, _count in counter.most_common(4):
        examples.append(
            {
                "title": _truncate_title(text),
                "description": suffix,
                "prompt": text,
            }
        )
    return examples


def _build_theme_examples(
    mode: str, task_texts: Iterable[str], memory_texts: Iterable[str]
) -> tuple[list[dict[str, str]], int]:
    combined_text = " ".join([*task_texts, *memory_texts]).lower()
    themed: list[tuple[int, dict[str, str]]] = []
    for theme in THEME_LIBRARY[mode]:
        score = sum(combined_text.count(keyword.lower()) for keyword in theme["keywords"])
        if score > 0:
            themed.append(
                (
                    score,
                    {
                        "title": str(theme["title"]),
                        "description": str(theme["description"]),
                        "prompt": str(theme["prompt"]),
                    },
                )
            )

    themed.sort(key=lambda item: item[0], reverse=True)
    return [example for _score, example in themed], sum(score for score, _ in themed)


def _dedupe_examples(examples: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for example in examples:
        key = _normalize_text(example["prompt"]).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(example)
    return deduped


def _build_mode_profile(mode: str, task_texts: list[str], memory_texts: list[str]) -> dict[str, Any]:
    task_examples = _build_task_examples(mode, task_texts)
    themed_examples, memory_match_score = _build_theme_examples(mode, task_texts, memory_texts)
    examples = _dedupe_examples([*task_examples, *themed_examples])[:4]

    source_task_count = len(task_texts)
    source_memory_count = len(memory_texts)
    confidence = min(
        1.0,
        round(
            (
                0.18 * len(examples)
                + 0.025 * min(source_task_count, 12)
                + 0.01 * min(memory_match_score, 20)
            ),
            2,
        ),
    )

    evidence_summary = {
        "source_task_count": source_task_count,
        "source_memory_count": source_memory_count,
        "top_task_texts": task_texts[:5],
    }

    return {
        "recommended_examples": examples,
        "confidence": confidence,
        "source_task_count": source_task_count,
        "source_memory_count": source_memory_count,
        "evidence_summary": evidence_summary,
        "fallback_needed": len(examples) < 4 or confidence < 0.45,
    }


def regenerate_task_prompt_recommendations(db: Session, user_id: int) -> dict[str, Any]:
    task_texts_by_mode = _extract_recent_task_texts(db, user_id)
    memory_texts = _extract_memory_texts(user_id)

    existing_rows = (
        db.query(TaskPromptRecommendation)
        .filter(TaskPromptRecommendation.user_id == user_id)
        .all()
    )
    rows_by_mode = {row.mode: row for row in existing_rows}

    results: dict[str, Any] = {}
    for mode in SUPPORTED_MODES:
        payload = _build_mode_profile(mode, task_texts_by_mode.get(mode, []), memory_texts)
        row = rows_by_mode.get(mode)
        if row is None:
            row = TaskPromptRecommendation(user_id=user_id, mode=mode)
            db.add(row)

        row.recommended_examples = payload["recommended_examples"]
        row.evidence_summary = payload["evidence_summary"]
        row.confidence = payload["confidence"]
        row.source_task_count = payload["source_task_count"]
        row.source_memory_count = payload["source_memory_count"]
        row.last_updated_at = _utc_now()

        results[mode] = payload

    db.commit()
    return serialize_task_prompt_recommendations(db, user_id)


def serialize_task_prompt_recommendations(db: Session, user_id: int) -> dict[str, Any]:
    rows = (
        db.query(TaskPromptRecommendation)
        .filter(TaskPromptRecommendation.user_id == user_id)
        .all()
    )
    rows_by_mode = {row.mode: row for row in rows}

    serialized: dict[str, Any] = {}
    for mode in SUPPORTED_MODES:
        row = rows_by_mode.get(mode)
        examples = row.recommended_examples if row and isinstance(row.recommended_examples, list) else []
        confidence = float(row.confidence) if row and row.confidence is not None else 0.0
        serialized[mode] = {
            "recommended_examples": examples,
            "confidence": confidence,
            "fallback_needed": len(examples) < 4 or confidence < 0.45,
            "last_updated_at": row.last_updated_at.isoformat() if row and row.last_updated_at else None,
            "evidence_summary": row.evidence_summary if row else None,
        }

    return serialized


def get_task_prompt_recommendations(db: Session, user_id: int) -> dict[str, Any]:
    rows = (
        db.query(TaskPromptRecommendation)
        .filter(TaskPromptRecommendation.user_id == user_id)
        .all()
    )
    if len(rows) != len(SUPPORTED_MODES):
        return regenerate_task_prompt_recommendations(db, user_id)

    now = _utc_now()
    for row in rows:
        last_updated = row.last_updated_at
        if last_updated is None:
            return regenerate_task_prompt_recommendations(db, user_id)
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        if now - last_updated > PROFILE_STALE_AFTER:
            return regenerate_task_prompt_recommendations(db, user_id)

    return serialize_task_prompt_recommendations(db, user_id)
