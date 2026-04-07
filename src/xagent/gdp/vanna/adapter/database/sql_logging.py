"""SQL 诊断日志工具。

职责边界：
- 为平台自身 ORM 数据库和外部数据源 SQL 执行提供独立日志文件；
- 通过 SQLAlchemy 事件记录应用数据库的真实执行轨迹；
- 给 SQL 工具补充策略判定、执行结果、耗时等平台语义，便于排查审批和外部数据源问题。
"""

from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from xagent.core.utils.security import redact_sensitive_text, redact_url_credentials_for_logging

SQL_LOGGER_NAME = "xagent.sql"
_SQL_LOGGING_CONFIGURED = False
_SQL_QUERY_LOGGER: SQLQueryLogger | None = None


def is_sql_logging_enabled() -> bool:
    """判断是否启用独立 SQL 日志。"""
    return os.getenv("ENABLE_SQL_LOGGING", "false").lower() == "true"


def _truncate_sql(text: str, limit: int = 4000) -> str:
    cleaned = " ".join(str(text).split())
    cleaned = redact_sensitive_text(cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}...(truncated)"


def _sanitize_sql_params(params: Any) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return {
            str(key): redact_sensitive_text(str(value)) for key, value in params.items()
        }
    if isinstance(params, (list, tuple)):
        return [redact_sensitive_text(str(value)) for value in params[:20]]
    return redact_sensitive_text(str(params))


def _json_safe(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def setup_sql_logging(
    log_file: str = "sql.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """配置独立 SQL 日志文件。"""
    global _SQL_LOGGING_CONFIGURED

    sql_logger = logging.getLogger(SQL_LOGGER_NAME)
    if _SQL_LOGGING_CONFIGURED:
        return sql_logger

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    sql_logger.setLevel(log_level)
    sql_logger.addHandler(file_handler)
    sql_logger.propagate = False
    sql_logger.info("SQL 独立日志已启用: %s", log_file)

    _SQL_LOGGING_CONFIGURED = True
    return sql_logger


def setup_sql_logging_from_env() -> bool:
    """根据环境变量启用 SQL 独立日志。"""
    if not is_sql_logging_enabled():
        return False

    setup_sql_logging(
        log_file=os.getenv("SQL_LOG_FILE", "sql.log"),
        log_level=logging.INFO,
        max_bytes=int(os.getenv("SQL_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        backup_count=int(os.getenv("SQL_LOG_BACKUP_COUNT", "5")),
    )
    return True


def get_sql_logger() -> logging.Logger:
    """获取 SQL logger，并在需要时做懒初始化。"""
    setup_sql_logging_from_env()
    return logging.getLogger(SQL_LOGGER_NAME)


class SQLQueryLogger:
    """应用数据库 SQLAlchemy 事件日志。

    这里只记录平台 ORM/迁移实际发出的 SQL；外部数据源 SQL 由 SQL 工具主动打点。
    """

    def __init__(self, log_params: bool = True, log_results: bool = False):
        self.log_params = log_params
        self.log_results = log_results
        self._query_counter = 0
        self._registered_engine_ids: set[int] = set()

    def register_events(self, engine: Engine) -> None:
        engine_id = id(engine)
        if engine_id in self._registered_engine_ids:
            return

        event.listen(engine, "before_cursor_execute", self._before_cursor_execute)
        event.listen(engine, "after_cursor_execute", self._after_cursor_execute)
        event.listen(engine, "begin", self._on_begin)
        event.listen(engine, "commit", self._on_commit)
        event.listen(engine, "rollback", self._on_rollback)
        self._registered_engine_ids.add(engine_id)
        get_sql_logger().info("已注册应用数据库 SQL 事件监听器")

    def _before_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        self._query_counter += 1
        query_id = self._query_counter
        conn.info.setdefault("query_start_time", {})[query_id] = time.time()
        context._query_id = query_id

        payload: dict[str, Any] = {
            "query_id": query_id,
            "statement": _truncate_sql(statement),
            "executemany": executemany,
        }
        if self.log_params and parameters:
            payload["parameters"] = _sanitize_sql_params(parameters)
        get_sql_logger().info("[DB SQL start] %s", _json_safe(payload))

    def _after_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        query_id = getattr(context, "_query_id", None)
        start_time = conn.info.get("query_start_time", {}).pop(query_id, None)
        elapsed_ms = round((time.time() - start_time) * 1000, 2) if start_time else None

        payload: dict[str, Any] = {
            "query_id": query_id,
            "elapsed_ms": elapsed_ms,
            "rowcount": getattr(cursor, "rowcount", None),
        }
        if self.log_results and getattr(cursor, "description", None):
            payload["columns"] = [column[0] for column in cursor.description]
        get_sql_logger().info("[DB SQL end] %s", _json_safe(payload))

    def _on_begin(self, conn: Any) -> None:
        get_sql_logger().info("[DB transaction] begin")

    def _on_commit(self, conn: Any) -> None:
        get_sql_logger().info("[DB transaction] commit")

    def _on_rollback(self, conn: Any) -> None:
        get_sql_logger().warning("[DB transaction] rollback")


def enable_sql_logging(
    engine: Engine,
    log_params: bool = True,
    log_results: bool = False,
) -> None:
    """启用应用数据库 engine 的 SQL 事件日志。"""
    global _SQL_QUERY_LOGGER

    if not setup_sql_logging_from_env():
        return

    if _SQL_QUERY_LOGGER is None:
        _SQL_QUERY_LOGGER = SQLQueryLogger(
            log_params=log_params,
            log_results=log_results,
        )
    _SQL_QUERY_LOGGER.register_events(engine)


def log_sql_tool_event(event_name: str, **payload: Any) -> None:
    """记录外部数据源 SQL 工具事件。"""
    if not is_sql_logging_enabled():
        return

    setup_sql_logging_from_env()
    normalized_payload = dict(payload)
    if "query" in normalized_payload and normalized_payload["query"] is not None:
        normalized_payload["query"] = _truncate_sql(str(normalized_payload["query"]))
    if (
        "database_url" in normalized_payload
        and normalized_payload["database_url"] is not None
    ):
        normalized_payload["database_url"] = redact_url_credentials_for_logging(
            str(normalized_payload["database_url"])
        )
    get_sql_logger().info(
        "[SQL tool %s] %s", event_name, _json_safe(normalized_payload)
    )

