"""统一召回框架辅助工具。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.core.model.embedding.adapter import create_embedding_adapter
from xagent.core.model.storage.db.adapter import SQLAlchemyModelHub
from xagent.web.models.model import Model as DBModel
from xagent.web.services.model_service import get_default_embedding_model


def load_default_embedding_adapter(db: Session, user_id: int) -> Any | None:
    """加载当前用户默认 embedding adapter。"""

    model_id = get_default_embedding_model(user_id)
    if not model_id:
        return None
    try:
        config = SQLAlchemyModelHub(db, DBModel).load(model_id)
        return create_embedding_adapter(config)
    except Exception:
        return None
