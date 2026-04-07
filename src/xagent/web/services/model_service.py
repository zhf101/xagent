"""
Model service for providing model-related utilities.

This service provides centralized functionality for model resolution and management
across the xagent system with multi-tenant support.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from ...core.model.chat.basic.base import BaseLLM
from ...core.model.embedding.base import BaseEmbedding
from ...core.model.rerank.base import BaseRerank

logger = logging.getLogger(__name__)


def get_default_vision_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """
    Get the default vision model for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default vision model or None if not available
    """
    try:
        # Try to get from database (requires web context)
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        # This won't work in non-web contexts, so we'll fallback to environment
        try:
            # Try to get a database session (this might fail in CLI contexts)
            db = next(get_db())

            # If user_id is provided, get user-specific default
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

            # Fallback to admin defaults first, then other shared defaults
            admin_vision_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "visual",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_vision_defaults:
                return _create_llm_instance(admin_vision_defaults[0].model)

            # If no admin defaults, fallback to any shared defaults
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
            pass

    except ImportError:
        pass  # Web modules not available

    # No fallback to environment variables - require database configuration
    return None


def get_default_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """
    Get the default general model for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default general model or None if not available
    """
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            # If user_id is provided, get user-specific default
            if user_id:
                general_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "general",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if general_default and general_default.model:
                    return _create_llm_instance(general_default.model)

            # Fallback to admin defaults first, then other shared defaults
            admin_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "general",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_defaults:
                return _create_llm_instance(admin_defaults[0].model)

            # If no admin defaults, fallback to any shared defaults
            shared_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(UserDefaultModel.config_type == "general", UserModel.is_shared)
                .limit(1)
                .all()
            )

            if shared_defaults:
                return _create_llm_instance(shared_defaults[0].model)

        except Exception as e:
            logger.warning(f"Failed to get default model from database: {e}")
            pass

    except ImportError:
        pass

    # No fallback to environment variables - require database configuration
    return None


def get_fast_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """
    Get the default fast/small model for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default fast/small model or None if not available
    """
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            # If user_id is provided, get user-specific default
            if user_id:
                fast_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "small_fast",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if fast_default and fast_default.model:
                    return _create_llm_instance(fast_default.model)

            # Fallback to admin defaults first, then other shared defaults
            admin_fast_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "small_fast",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_fast_defaults:
                return _create_llm_instance(admin_fast_defaults[0].model)

            # If no admin defaults, fallback to any shared defaults
            shared_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "small_fast", UserModel.is_shared
                )
                .limit(1)
                .all()
            )

            if shared_defaults:
                return _create_llm_instance(shared_defaults[0].model)

        except Exception as e:
            logger.warning(f"Failed to get fast model from database: {e}")
            pass

    except ImportError:
        pass

    # For fast model, return None if not configured
    return None


def get_compact_model(user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """
    Get the default compact model for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default compact model or None if not available
    """
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_llm_instance

        try:
            db = next(get_db())

            # If user_id is provided, get user-specific default
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

            # Fallback to admin defaults first, then other shared defaults
            admin_compact_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "compact",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_compact_defaults:
                return _create_llm_instance(admin_compact_defaults[0].model)

            # If no admin defaults, fallback to any shared defaults
            shared_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(UserDefaultModel.config_type == "compact", UserModel.is_shared)
                .limit(1)
                .all()
            )

            if shared_defaults:
                return _create_llm_instance(shared_defaults[0].model)

        except Exception as e:
            logger.warning(f"Failed to get compact model from database: {e}")
            pass

    except ImportError:
        pass

    # For compact model, return None if not configured
    return None


def get_embedding_model(user_id: Optional[int] = None) -> Optional[BaseEmbedding]:
    """
    Get the default embedding adapter for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default embedding adapter or None if not available
    """
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_embedding_instance

        try:
            db = next(get_db())

            # If user_id is provided, get user-specific default
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
                    return _create_embedding_instance(embedding_default.model)

            # Fallback to admin defaults first, then other shared defaults
            admin_embedding_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "embedding",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_embedding_defaults:
                return _create_embedding_instance(admin_embedding_defaults[0].model)

            # If no admin defaults, fallback to any shared defaults
            shared_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "embedding", UserModel.is_shared
                )
                .limit(1)
                .all()
            )

            if shared_defaults:
                return _create_embedding_instance(shared_defaults[0].model)

        except Exception as e:
            logger.warning(f"Failed to get embedding model from database: {e}")
            pass

    except ImportError:
        pass

    # No fallback to environment variables - require database configuration
    return None


def get_rerank_model(user_id: Optional[int] = None) -> Optional[BaseRerank]:
    """
    Get the default rerank adapter for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The default rerank adapter or None if not available
    """
    try:
        from ..models.database import get_db
        from ..models.user import User, UserDefaultModel, UserModel
        from .llm_utils import _create_rerank_instance

        try:
            db = next(get_db())

            if user_id:
                rerank_default = (
                    db.query(UserDefaultModel)
                    .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                    .filter(
                        UserDefaultModel.user_id == user_id,
                        UserDefaultModel.config_type == "rerank",
                        UserModel.user_id == user_id,
                    )
                    .first()
                )

                if rerank_default and rerank_default.model:
                    return _create_rerank_instance(rerank_default.model)

            admin_rerank_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "rerank",
                    UserModel.is_shared,
                    UserDefaultModel.user_id.in_(
                        db.query(User.id).filter(User.is_admin)
                    ),
                )
                .limit(1)
                .all()
            )

            if admin_rerank_defaults:
                return _create_rerank_instance(admin_rerank_defaults[0].model)

            shared_defaults = (
                db.query(UserDefaultModel)
                .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
                .filter(
                    UserDefaultModel.config_type == "rerank",
                    UserModel.is_shared,
                )
                .limit(1)
                .all()
            )

            if shared_defaults:
                return _create_rerank_instance(shared_defaults[0].model)

        except Exception as e:
            logger.warning(f"Failed to get rerank model from database: {e}")
            pass

    except ImportError:
        pass

    return None


def get_vision_model(db: Session, user_id: Optional[int] = None) -> Optional[BaseLLM]:
    """
    Get vision model from database.

    Args:
        db: Database session
        user_id: User ID (currently ignored as models are shared)

    Returns:
        Vision model instance or None if not found
    """
    try:
        from sqlalchemy import String, cast, or_

        from ..models.model import Model as DBModel
        from .llm_utils import _create_llm_instance

        # Query models that have vision ability in their abilities JSON field
        db_model = (
            db.query(DBModel)
            .filter(
                DBModel.category == "llm",
                DBModel.is_active,
                or_(
                    cast(DBModel.abilities, String).contains('"vision"'),
                    cast(DBModel.abilities, String).like('%"vision"%'),
                ),
            )
            .first()
        )

        if db_model:
            return _create_llm_instance(db_model)
        return None

    except Exception as e:
        logger.error(f"Failed to get vision model from database: {e}")
        return None


def get_default_embedding_model(user_id: Optional[int] = None) -> Optional[str]:
    """
    Get the default embedding model ID for a specific user.

    Args:
        user_id: User ID for multi-tenant model resolution. If None, uses admin defaults.

    Returns:
        The embedding model ID or None if not available
    """
    from ..models.database import get_db
    from ..models.user import User, UserDefaultModel, UserModel

    db = next(get_db())

    # If user_id is provided, get user-specific default
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
            return str(embedding_default.model.model_id)

    # Admin defaults
    admin_embedding_defaults = (
        db.query(UserDefaultModel)
        .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
        .filter(
            UserDefaultModel.config_type == "embedding",
            UserModel.is_shared,
            UserDefaultModel.user_id.in_(db.query(User.id).filter(User.is_admin)),
        )
        .limit(1)
        .all()
    )

    if admin_embedding_defaults:
        return str(admin_embedding_defaults[0].model.model_id)

    # Any shared defaults
    embedding_models = (
        db.query(UserDefaultModel)
        .join(UserModel, UserDefaultModel.model_id == UserModel.model_id)
        .filter(UserDefaultModel.config_type == "embedding", UserModel.is_shared)
        .limit(1)
        .all()
    )

    if embedding_models:
        return str(embedding_models[0].model.model_id)

    return None
