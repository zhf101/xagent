"""OpenViking 同步辅助函数。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

from .service import get_openviking_service

logger = logging.getLogger(__name__)


def _normalize_filename(filename: str) -> str:
    """把文件名压成 URI 里更稳妥的形式。"""

    safe_name = Path(filename).name
    return safe_name.replace("/", "_").replace("\\", "_").replace(" ", "_")


def build_kb_resource_target_uri(
    *,
    user_id: int,
    collection: str,
    file_id: str,
    filename: str,
) -> str:
    """构造 xagent KB 文件在 OpenViking 中的资源 URI。"""

    normalized_filename = _normalize_filename(filename)
    return (
        "viking://resources/"
        f"xagent/kb/user_{user_id}/{collection}/{file_id}_{normalized_filename}"
    )


async def sync_kb_resource_to_openviking(
    *,
    user_id: int,
    file_path: str,
    collection: str,
    file_id: str,
    filename: str,
) -> dict[str, Any] | None:
    """把 KB 文件同步到 OpenViking。"""

    service = get_openviking_service()
    if not (service.is_enabled() and service.settings.resource_sync_enabled):
        return None

    target_uri = build_kb_resource_target_uri(
        user_id=user_id,
        collection=collection,
        file_id=file_id,
        filename=filename,
    )
    return await service.add_resource_from_local_file(
        user_id=user_id,
        agent_id=f"xagent-kb-user-{user_id}",
        file_path=file_path,
        to=target_uri,
        reason="Synced from xagent knowledge base ingestion",
        instruction=(
            "This file comes from xagent knowledge base ingestion. "
            f"Collection={collection}, file_id={file_id}, filename={filename}"
        ),
        wait=False,
    )


async def sync_skills_to_openviking(
    *,
    user_id: int | str,
    skills: Iterable[dict[str, Any]],
) -> int:
    """把一组 skill 同步到 OpenViking。

    返回成功提交的 skill 数量。单个 skill 失败不会中断整个同步流程。
    """

    service = get_openviking_service()
    if not (service.is_enabled() and service.settings.skill_index_enabled):
        return 0

    synced = 0
    for skill in skills:
        try:
            payload = {
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
                "content": skill.get("content", ""),
                "tags": skill.get("tags", []),
                "source_path": skill.get("path", ""),
                "files": skill.get("files", []),
            }
            await service.add_skill(
                user_id=user_id,
                agent_id="xagent-skill-sync",
                data=payload,
                wait=False,
            )
            synced += 1
        except Exception as exc:
            logger.warning(
                "Failed to sync skill '%s' to OpenViking: %s",
                skill.get("name"),
                exc,
            )
    return synced
