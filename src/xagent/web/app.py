"""Web 应用主入口。

这个文件的职责非常克制：它只负责把各业务模块接到 FastAPI 生命周期上，
而不在这里承载具体领域逻辑。

为什么要强调这一点？
- 新同学第一次看项目时，最容易把 `app.py` 当成“随手堆逻辑”的总控文件
- 一旦把业务判断、数据库编排、第三方初始化都塞进来，后续排查启动问题会非常痛苦

因此这里主要做四件事：
1. 创建 FastAPI app
2. 注册异常处理、中间件、静态资源
3. 挂载各业务 router
4. 在 startup/shutdown 中编排系统级初始化与回收
"""

import asyncio
import logging
import os
from contextlib import suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import get_uploads_dir
from ..core.model.chat.logging_callback import setup_llm_logging_from_env
from .api.admin_users import router as admin_users_router
from .api.agents import router as agents_router
from .api.auth import auth_router
from .api.channel import router as channel_router
from .api.chat import chat_router
from .api.files import file_router
from ..gdp.hrun.api.http_assets import router as gdp_http_assets_router
from .api.kb import kb_router
from .api.mcp import mcp_router
from .api.memory import MemoryManagementRouter
from .api.model import model_router
from .api.monitor import monitor_router
from .api.progress_ws import progress_ws_router
from .api.skills import router as skills_router
from .api.system import system_router
from .api.system_registry import router as system_registry_router
from .api.templates import router as templates_router
from ..gdp.vanna.api.text2sql import text2sql_router
from .api.tools import tools_router
from ..gdp.vanna.api.vanna_assets import router as vanna_assets_router
from ..gdp.vanna.api.vanna_sql import vanna_router
from .api.websocket import ws_router
from ..gdp.vanna.adapter.database.sql_logging import (
    enable_sql_logging,
    is_sql_logging_enabled,
)
from .dynamic_memory_store import get_memory_store
from .logging_config import setup_logging
from .models.database import get_engine, init_db

# Configure logging when running under gunicorn/uwsgi (no __main__.py)
setup_logging()  # Uses XAGENT_LOG_LEVEL env var or defaults to INFO
setup_llm_logging_from_env()

logger = logging.getLogger(__name__)


__all__ = ["app"]


# Ensure web, uploads directory exists before configuring static files
uploads_dir = get_uploads_dir()
uploads_dir.mkdir(parents=True, exist_ok=True)


# FastAPI app creation here
app = FastAPI(
    title="xagent", description="The Agent Operating System", redirect_slashes=False
)

# Track background migration task for graceful shutdown cleanup.
_migration_task: asyncio.Task[None] | None = None


@app.get("/health")
async def health_check() -> dict[str, str]:
    """容器探活接口。

    这里只返回最小成功信号，不做数据库、模型、外部依赖的深探测，
    避免健康检查本身反过来拖垮服务。
    """
    return {"status": "ok"}


# Add global exception handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """统一处理请求参数校验异常。

    这里的核心目标不是“美化报错”，而是保证异常内容一定可 JSON 序列化。
    某些上传/二进制场景下，FastAPI 原始错误对象里可能混入不可序列化值，
    如果不先做清洗，异常处理器自己反而会再次抛错。
    """
    import traceback

    logger.error(f"Validation error in {request.url}: {str(exc)}")
    logger.error(f"Traceback: {traceback.format_exc()}")

    # Sanitize error details to remove binary data and non-serializable objects
    sanitized_errors = []
    for error in exc.errors():
        sanitized_error = {}
        for key, value in error.items():
            # Try to serialize each value to check if it's JSON-serializable
            try:
                import json

                json.dumps(value)
                sanitized_error[key] = value
            except (TypeError, ValueError):
                # If not serializable, convert to string representation
                if key == "ctx" and isinstance(value, dict):
                    # Special handling for ctx dict - sanitize each sub-value
                    sanitized_ctx = {}
                    for ctx_key, ctx_value in value.items():
                        if isinstance(ctx_value, Exception):
                            sanitized_ctx[ctx_key] = str(ctx_value)
                        else:
                            try:
                                json.dumps(ctx_value)
                                sanitized_ctx[ctx_key] = ctx_value
                            except (TypeError, ValueError):
                                sanitized_ctx[ctx_key] = str(ctx_value)
                    sanitized_error[key] = sanitized_ctx
                else:
                    sanitized_error[key] = str(value)
        sanitized_errors.append(sanitized_error)

    return JSONResponse(
        status_code=422,
        content={"detail": sanitized_errors},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> None:
    """全局兜底异常处理器。

    这里选择“记录后继续抛出”，而不是直接吞掉异常返回统一文案，
    原因是上层仍然需要保留 FastAPI / Starlette 的默认错误传播行为，
    否则很多调试信息会被吃掉。
    """
    import traceback

    logger.error(f"Unhandled exception in {request.url}: {str(exc)}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    # Re-raise the exception, let FastAPI handle it
    raise exc


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: "*" should not be used in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_dir = os.path.dirname(os.path.abspath(__file__))

# For static files
app.mount(
    "/uploads",
    StaticFiles(directory=str(uploads_dir)),
    name="uploads",
)

# memory 管理路由需要延迟绑定 memory store getter，
# 这样启动后如果 embedding model 或 vector backend 发生切换，
# 路由里拿到的仍然是当前有效的 store，而不是启动瞬间的旧实例。
memory_router = MemoryManagementRouter(get_memory_store).get_router()

# API routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(file_router)
app.include_router(kb_router)
app.include_router(model_router)
app.include_router(ws_router)
app.include_router(monitor_router)
app.include_router(progress_ws_router)
app.include_router(memory_router)
app.include_router(mcp_router)
app.include_router(text2sql_router)
app.include_router(tools_router)
app.include_router(admin_users_router)
app.include_router(skills_router)
app.include_router(system_router)
app.include_router(system_registry_router)
app.include_router(templates_router)
app.include_router(agents_router)
app.include_router(gdp_http_assets_router)
app.include_router(vanna_assets_router)
app.include_router(vanna_router)
app.include_router(channel_router, prefix="/api/channels", tags=["Channels"])


# initial database and skill manager
@app.on_event("startup")
async def startup_event() -> None:
    """应用启动编排。

    这里做的都是“系统级一次性初始化”，例如：
    - 数据库 schema 初始化
    - skill/template manager 准备
    - memory store 类型日志输出
    - 向量库迁移任务、渠道初始化、sandbox 初始化

    约束：
    - 业务 CRUD 绝不能放进这里
    - 任何可能失败的外围能力都应尽量降级，而不是直接阻塞整个 Web 服务启动
    """
    global _migration_task
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully")
    if is_sql_logging_enabled():
        enable_sql_logging(
            engine=get_engine(),
            log_params=os.getenv("SQL_LOG_QUERY_PARAMS", "true").lower() == "true",
            log_results=os.getenv("SQL_LOG_RESULTS", "false").lower() == "true",
        )
        logger.info("SQL logging enabled")

    # Initialize skill manager
    from ..skills.utils import create_skill_manager

    skill_manager = create_skill_manager()
    await skill_manager.initialize()
    app.state.skill_manager = skill_manager
    logger.info(
        f"Skill manager initialized with {len(await skill_manager.list_skills())} skills"
    )

    # Initialize template manager
    from ..templates.utils import create_template_manager

    template_manager = create_template_manager()
    await template_manager.initialize()
    app.state.template_manager = template_manager
    logger.info(
        f"Template manager initialized with {len(await template_manager.list_templates())} templates"
    )

    # memory store 会根据 embedding model 和 vector backend 动态切换。
    # 启动时把当前实际落地的 store 类型打到日志里，方便排查“为什么这次没有向量检索”。
    from .dynamic_memory_store import get_memory_store_manager

    manager = get_memory_store_manager()
    store_info = manager.get_store_info()

    if store_info["is_lancedb"]:
        backend_name = store_info.get("vector_backend") or "lancedb"
        logger.info(
            "Using %s memory store with vector search capabilities", backend_name
        )
        logger.info(f"Embedding model ID: {store_info['embedding_model_id']}")
    else:
        logger.info("Using in-memory store (no vector search capabilities)")

    logger.info(
        f"Memory store similarity threshold: {store_info['similarity_threshold']}"
    )

    # 向量库结构迁移是潜在耗时动作，因此默认关闭，只在显式环境变量开启时执行。
    # 这里保留后台异步任务句柄，shutdown 时需要尝试优雅回收。
    auto_migrate = os.getenv("LANCEDB_AUTO_MIGRATE", "false").lower() == "true"

    try:
        from ..core.tools.core.RAG_tools.LanceDB.schema_manager import (
            check_table_needs_migration,
        )
        from ..providers.vector_store.lancedb import get_connection_from_env

        conn = get_connection_from_env()

        # Check if any tables need migration
        needs_migration = False
        tables_to_check = [
            "chunks",
            "documents",
            "parses",
            "ingestion_runs",
            "prompt_templates",
        ]
        tables_need_migration_list = []

        for table_name in tables_to_check:
            if check_table_needs_migration(conn, table_name):
                logger.warning(
                    "Table '%s' needs migration (missing user_id field)",
                    table_name,
                )
                tables_need_migration_list.append(table_name)
                needs_migration = True

        # Check embeddings tables (use shared compat helper)
        if not needs_migration:
            try:
                from ..core.tools.core.RAG_tools.utils.lancedb_query_utils import (
                    list_embeddings_table_names,
                )

                for table_name in list_embeddings_table_names(conn):
                    if check_table_needs_migration(conn, table_name):
                        logger.warning(
                            "Table '%s' needs migration (missing user_id field)",
                            table_name,
                        )
                        tables_need_migration_list.append(table_name)
                        needs_migration = True
            except Exception as e:
                logger.warning("Could not check embeddings tables: %s", e)

        if needs_migration:
            if tables_need_migration_list:
                logger.warning(
                    "Tables requiring migration: %s",
                    ", ".join(tables_need_migration_list),
                )

            if auto_migrate:
                # Run migration in background to avoid blocking startup
                logger.info("=" * 60)
                logger.info("STARTING BACKGROUND LANCEDB MIGRATION")
                logger.info("=" * 60)
                logger.info(
                    "Tables requiring migration: %s",
                    ", ".join(tables_need_migration_list),
                )

                async def run_migration_background() -> None:
                    from ..migrations.lancedb.backfill_user_id import backfill_all

                    try:
                        result = await asyncio.to_thread(backfill_all, dry_run=False)
                        logger.info("=" * 60)
                        logger.info("BACKGROUND LANCEDB MIGRATION COMPLETED")
                        logger.info("=" * 60)
                        logger.info(
                            "Migration results: chunks=%s backfilled, embeddings=%s backfilled",
                            result.get("chunks", {}).get("backfilled", 0),
                            result.get("embeddings", {}).get("backfilled", 0),
                        )

                        # Log any skipped records
                        chunks_skipped = result.get("chunks", {}).get("skipped", 0)
                        embeddings_skipped = result.get("embeddings", {}).get(
                            "skipped", 0
                        )
                        if chunks_skipped > 0 or embeddings_skipped > 0:
                            logger.warning(
                                "Some records were skipped (no matching document): chunks=%s, embeddings=%s",
                                chunks_skipped,
                                embeddings_skipped,
                            )
                    except Exception as e:
                        logger.error("=" * 60)
                        logger.error("BACKGROUND LANCEDB MIGRATION FAILED")
                        logger.error("=" * 60)
                        logger.error("Error: %s", e, exc_info=True)
                        logger.warning(
                            "Some features may not work correctly. "
                            "Please run migration manually: python -m xagent.migrations.lancedb.backfill_user_id"
                        )

                # Start background task without awaiting, but keep a reference
                # so shutdown can cancel/await it gracefully.
                _migration_task = asyncio.create_task(run_migration_background())
            else:
                logger.warning(
                    "LANCEDB_AUTO_MIGRATE is disabled. "
                    "Migration will NOT run automatically. "
                    "To enable automatic migration, set LANCEDB_AUTO_MIGRATE=true. "
                    "To run migration manually: python -m xagent.migrations.lancedb.backfill_user_id"
                )
        else:
            logger.info("LanceDB tables are up to date, no migration needed")
    except Exception as e:
        logger.warning(
            "Could not check LanceDB migration status: %s. "
            "Application will continue, but some features may not work correctly.",
            e,
        )

    # Warmup sandbox manager
    from .sandbox_manager import get_sandbox_manager

    sandbox_mgr = get_sandbox_manager()
    if sandbox_mgr:
        await sandbox_mgr.cleanup()
        await sandbox_mgr.warmup()
        logger.info("Sandbox manager initialized and warmed up")
    else:
        logger.info("Sandbox manager not available (disabled or init failed)")

    # Start Telegram and FeiShu channels if enabled
    try:
        from .channels.feishu.bot import get_feishu_channel
        from .channels.telegram.bot import get_telegram_channel

        telegram_channel = get_telegram_channel()
        if telegram_channel.enabled:
            logger.info("Initializing Telegram channel manager...")
            app.state.telegram_task = asyncio.create_task(telegram_channel.start())
            logger.info("Telegram channel background task created successfully")

        feishu_channel = get_feishu_channel()
        if feishu_channel.enabled:
            logger.info("Initializing Feishu channel manager...")
            app.state.feishu_task = asyncio.create_task(feishu_channel.start())
            logger.info("Feishu channel background task created successfully")
    except Exception as e:
        logger.error(f"Failed to start Telegram channel manager: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """应用关闭编排。

    shutdown 的目标不是“把所有资源都强制关死”，而是尽量优雅回收：
    - 停掉后台迁移任务
    - 关闭外部 channel
    - 释放 sandbox / manager 等长生命周期对象
    """
    global _migration_task

    if _migration_task and not _migration_task.done():
        logger.info("Cancelling background LanceDB migration task...")
        _migration_task.cancel()
        with suppress(asyncio.CancelledError):
            await _migration_task
    _migration_task = None

    # Shutdown Telegram channel if enabled
    try:
        if hasattr(app.state, "telegram_task"):
            app.state.telegram_task.cancel()
            logger.info("Cancelled Telegram polling task")

        from .channels.feishu.bot import get_feishu_channel
        from .channels.telegram.bot import get_telegram_channel

        telegram_channel = get_telegram_channel()
        if telegram_channel.enabled:
            await telegram_channel.stop()
            logger.info("Telegram channel stopped successfully")

        feishu_channel = get_feishu_channel()
        await feishu_channel.stop()
    except Exception as e:
        logger.error("Failed to stop Telegram channel: %s", e, exc_info=True)

    # Shutdown all sandboxes
    from .sandbox_manager import get_sandbox_manager

    sandbox_mgr = get_sandbox_manager()
    if sandbox_mgr:
        await sandbox_mgr.cleanup()


# Frontend is now served by Next.js at http://localhost:3000
# This backend only provides API endpoints


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
