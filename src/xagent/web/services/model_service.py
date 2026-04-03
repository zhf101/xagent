"""
Model service for providing model-related utilities.

This service provides centralized functionality for model resolution and management
across the xagent system with multi-tenant support.
"""

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from xagent.web.api.model import DBModel

from ...core.model.chat.basic.base import BaseLLM
from ...core.model.embedding.base import BaseEmbedding

logger = logging.getLogger(__name__)


def get_default_vision_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """Get the default vision model for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            if user_id:
                vision_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "visual",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if vision_default and vision_default.model:
                    return _create_llm_instance(vision_default.model)

            admin_vision_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "visual",
                    UserModel.is_owner == True,
                )
                .all()
            )

            if admin_vision_defaults:
                return _create_llm_instance(admin_vision_defaults[0].model)

            vision_models = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(UserDefaultModel.config_type == "visual", UserModel.is_shared)
                .limit(1)
                .all()
            )

            if vision_models:
                return _create_llm_instance(vision_models[0].model)

        except Exception as e:
            logger.warning(f"Failed to get vision model from database: {e}")

    except ImportError:
        pass

    return None


def get_default_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """Get the default LLM model for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            if user_id:
                default_model = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "chat",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if default_model and default_model.model:
                    return _create_llm_instance(default_model.model)

            admin_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "chat",
                    UserModel.is_owner == True,
                )
                .all()
            )

            if admin_defaults:
                return _create_llm_instance(admin_defaults[0].model)

            shared_models = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(UserDefaultModel.config_type == "chat", UserModel.is_shared)
                .limit(1)
                .all()
            )

            if shared_models:
                return _create_llm_instance(shared_models[0].model)

        except Exception as e:
            logger.warning(f"Failed to get default model from database: {e}")

    except ImportError:
        pass

    return None


def get_fast_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """Get the fast LLM model for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            if user_id:
                fast_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "fast",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if fast_default and fast_default.model:
                    return _create_llm_instance(fast_default.model)

        except Exception as e:
            logger.warning(f"Failed to get fast model from database: {e}")

    except ImportError:
        pass

    return get_default_model(user_id)


def get_compact_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """Get the compact LLM model for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            if user_id:
                compact_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "compact",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if compact_default and compact_default.model:
                    return _create_llm_instance(compact_default.model)

        except Exception as e:
            logger.warning(f"Failed to get compact model from database: {e}")

    except ImportError:
        pass

    return get_default_model(user_id)


def get_embedding_model(user_id: Optional[int] = None) -> Optional[BaseEmbedding]:
    """Get the embedding model for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from xagent.core.model.embedding.adapter import create_embedding_adapter
        from xagent.core.model.model import EmbeddingModelConfig

        try:
            db = next(get_db())

            if user_id:
                embedding_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "embedding",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if embedding_default and embedding_default.model:
                    model = embedding_default.model
                    config = EmbeddingModelConfig(
                        id=model.model_id,
                        model_name=model.model_name,
                        api_key=model.api_key,
                        base_url=model.base_url,
                    )
                    return create_embedding_adapter(config)

        except Exception as e:
            logger.warning(f"Failed to get embedding model from database: {e}")

    except ImportError:
        pass

    return None


def get_vision_model(db: Session, user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """Get the vision model for a specific user."""
    return get_default_vision_model(user_id)


def get_models_by_category(category: str, db: Session) -> list:
    """Get all models by category."""
    return (
        db.query(DBModel)
        .filter(DBModel.category == category, DBModel.is_active == True)
        .all()
    )


def get_default_embedding_model(user_id: Optional[int] = None) -> Optional[str]:
    """Get the default embedding model ID for a specific user."""
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel

        try:
            db = next(get_db())

            if user_id:
                embedding_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "embedding",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if embedding_default and embedding_default.model:
                    return embedding_default.model.model_id

        except Exception as e:
            logger.warning(f"Failed to get embedding model from database: {e}")

    except ImportError:
        pass

    return None