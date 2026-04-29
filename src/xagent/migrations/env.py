import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# 从 .env 文件加载环境变量
load_dotenv()

# 将父目录添加到路径以便导入模块
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from xagent.core.storage import get_default_db_url

# 导入所有模型以确保它们注册到 Base.metadata
# 这些导入禁用了类型检查，因为它们由 Alembic 动态加载
# flake8: noqa: E402
from xagent.web import models as web_models  # noqa: F401
from xagent.web.models.database import Base

# 导入 dev0407 分支新增的模型，确保 Alembic 能识别这些表
from xagent.gdp.vanna.model.vanna import (  # noqa: F401
    VannaKnowledgeBase,
    VannaSchemaHarvestJob,
    VannaSchemaTable,
    VannaSchemaColumn,
    VannaSchemaColumnAnnotation,
    VannaTrainingEntry,
    VannaEmbeddingChunk,
    VannaAskRun,
    VannaSqlAsset,
    VannaSqlAssetVersion,
    VannaSqlAssetRun,
)
from xagent.gdp.hrun.model.http_resource import GdpHttpResource  # noqa: F401

# Alembic Config 对象，提供对
# 当前使用的 .ini 文件中值的访问。
config = context.config

# 解析配置文件用于 Python 日志记录。
# 此行基本设置日志记录器。
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 使用我们模型的 MetaData 支持自动生成
target_metadata = Base.metadata

# 来自配置的其他值，根据 env.py 的需要定义，
# 可以获取：
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """以离线模式运行迁移。

    仅使用 URL（而非 Engine）配置上下文
    尽管 Engine 也是可接受的
    通过跳过 Engine 创建，
    我们甚至不需要 DBAPI 可用。

    对 context.execute() 的调用在此处将给定字符串输出到
    脚本输出。

    """
    url = config.get_main_option("sqlalchemy.url")
    if url is None:
        # 遵循 DATABASE_URL 环境变量
        url = os.getenv("DATABASE_URL")
        if url is None:
            url = get_default_db_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以在线模式运行迁移。

    在这种场景下，我们需要创建一个 Engine
    并将连接关联到上下文。

    """
    # 检查是否通过 config.attributes 提供了连接
    connection = config.attributes.get("connection", None)

    if connection is not None:
        # 使用提供的连接
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    else:
        # 回退：使用配置中的 URL 创建新连接
        configuration = config.get_section(config.config_ini_section, {})
        if configuration.get("sqlalchemy.url") is None:
            # 遵循 DATABASE_URL 环境变量
            url = os.getenv("DATABASE_URL")
            if url is None:
                url = get_default_db_url()
            configuration["sqlalchemy.url"] = url

        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
