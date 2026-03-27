"""@ 提及（Mention）查询接口。

为前端聊天输入框的 @ 能力提供统一数据源。
支持的类别：环境、系统、数据库、模板。
- 环境：从通用字典表 rtp_dict（DICTTYPE='ENV_TYPE'）加载
- 系统：从 biz_systems 表加载
- 数据库：从 text2sql_databases 表加载
- 模板：从 datamakepool_templates 表加载（仅已发布）
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User

logger = logging.getLogger(__name__)

mentions_router = APIRouter(prefix="/api/mentions", tags=["mentions"])

MentionCategory = Literal["system", "database", "template", "environment"]


def _query_environments(db: Session) -> List[Dict[str, Any]]:
    """从通用字典表 rtp_dict 查询环境列表（DICTTYPE='ENV_TYPE'）。"""
    from ..models.rtp_dict import RtpDict

    rows = (
        db.query(RtpDict)
        .filter(
            RtpDict.DICTTYPE == "ENV_TYPE",
            RtpDict.STATUS == 1,
        )
        .order_by(RtpDict.ORDER_SEQ, RtpDict.DICTCODE)
        .all()
    )
    return [
        {
            "id": row.DICTCODE,
            "label": f"{row.DICTCODE} - {row.DICTVALUE or row.DICTCODE}",
            "value": row.DICTCODE,
            "description": row.DICTVALUE or "",
        }
        for row in rows
    ]


def _query_systems(db: Session) -> List[Dict[str, Any]]:
    """查询业务系统字典，返回 system_short - system_name 列表。"""
    from ..models.biz_system import BizSystem

    rows = db.query(BizSystem).order_by(BizSystem.system_short).all()
    return [
        {
            "id": str(row.id),
            "label": f"{row.system_short} - {row.system_name}",
            "value": row.system_short,
            "description": row.system_name,
        }
        for row in rows
    ]


def _query_databases(db: Session, user: User) -> List[Dict[str, Any]]:
    """查询当前用户可见的已启用数据源。"""
    from ..models.text2sql import Text2SQLDatabase

    rows = (
        db.query(Text2SQLDatabase)
        .filter(
            Text2SQLDatabase.enabled.is_(True),
        )
        .order_by(Text2SQLDatabase.name)
        .all()
    )
    return [
        {
            "id": str(row.id),
            "label": row.name,
            "value": row.name,
            "description": f"{row.type.value}"
            + (f" · {row.system.system_short}" if row.system else ""),
        }
        for row in rows
    ]


def _query_templates(db: Session) -> List[Dict[str, Any]]:
    """查询已发布（可直接使用）的造数模板。"""
    inspector = inspect(db.bind)
    if "datamakepool_templates" not in inspector.get_table_names():
        return []

    rows = db.execute(
        text(
            """
            SELECT id, name, system_short, current_version
            FROM datamakepool_templates
            WHERE status = 'published'
            ORDER BY id DESC
            """
        )
    ).mappings()

    return [
        {
            "id": str(row["id"]),
            "label": row["name"],
            "value": str(row["id"]),
            "description": (row.get("system_short") or "")
            + (f" · v{row.get('current_version', 1)}" if row.get("current_version") else ""),
        }
        for row in rows
    ]


# 类别 → 查询函数映射（database 需要 user 参数，单独处理）
_CATEGORY_HANDLERS = {
    "environment": _query_environments,
    "system": _query_systems,
    "template": _query_templates,
}


@mentions_router.get("")
async def list_mentions(
    category: MentionCategory = Query(..., description="提及类别：environment / system / database / template"),
    q: str = Query("", description="搜索关键词（可选）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """根据类别返回 @ 提及候选列表。

    返回格式统一为：
    ```json
    [
      {"id": "YD01", "label": "YD01 - YD01环境", "value": "YD01", "description": "YD01环境"}
    ]
    ```
    """
    try:
        if category == "database":
            items = _query_databases(db, user)
        else:
            handler = _CATEGORY_HANDLERS.get(category)
            if not handler:
                return []
            items = handler(db)
    except Exception as e:
        logger.error(f"[mentions] Failed to query category={category}: {e}", exc_info=True)
        return []

    # 关键词过滤
    if q:
        lower_q = q.lower()
        items = [
            item
            for item in items
            if lower_q in item["label"].lower()
            or lower_q in item.get("description", "").lower()
            or lower_q in item.get("value", "").lower()
        ]

    return items
