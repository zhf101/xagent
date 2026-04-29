import logging
from typing import Any, Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from ...config import get_database_url

_SessionLocal: sessionmaker[Session] | None = None

_engine: Engine | None = None

# 创建基础模型类
# Mypy 变通方案: 将 Base 显式类型标注为 Any,避免 "variable not valid as type" 错误
Base: Any = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话"""
    if _SessionLocal is None:
        raise RuntimeError("Session Local is not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_local() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Session Local is not initialized. Call init_db() first.")
    return _SessionLocal


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine is not initialized. Call init_db() first.")
    return _engine


def init_db(db_url: str | None = None) -> None:
    """初始化数据库,创建所有表并设置默认用户"""
    # 导入所有模型,确保它们注册到 Base.metadata
    from . import (  # noqa: F401
        MCPServer,
        Model,
        OAuthProvider,
        PublicMCPApp,
        SystemSetting,
        Task,
        TaskChatMessage,
        TemplateStats,
        ToolConfig,
        ToolUsage,
        UploadedFile,
        User,
        UserDefaultModel,
        UserModel,
    )
    from .agent import Agent  # noqa: F401
    from .sandbox import SandboxInfo, SandboxSnapshot  # noqa: F401
    from xagent.gdp.vanna.model.text2sql import Text2SQLDatabase  # noqa: F401

    global _SessionLocal
    global _engine

    # 数据库配置
    if db_url is not None:
        database_url = db_url
    else:
        database_url = get_database_url()

    # 创建数据库引擎
    # SQLite 使用 NullPool 防止连接池问题
    # 其它数据库使用 QueuePool 并设置超时参数
    if "sqlite" in database_url:
        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=NullPool,  # SQLite doesn't need connection pooling
        )
    else:
        _engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,  # 从连接池获取连接的超时时间 30 秒
            pool_recycle=3600,  # 连接回收周期 1 小时
            pool_pre_ping=True,  # 使用前验证连接
        )

    # 创建会话工厂
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # 先尝试升级数据库到最新版本
    from ...db import try_upgrade_db

    try_upgrade_db(_engine)

    # 创建所有表
    Base.metadata.create_all(bind=_engine)

    logger = logging.getLogger(__name__)
    logger.info("Database initialized. Waiting for first admin setup.")
