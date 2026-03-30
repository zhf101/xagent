"""本地日志可观测性辅助工具。

该模块解决两类问题：

1. 通过 `contextvars` 维护请求 / 任务级上下文，让日志能按一次链路串起来看
2. 提供统一的事件日志格式，避免各模块各自手写不一致的日志文本

注意：
- 这里服务的是“本地排障可读性”，不是外部 tracing 平台
- 描述性内容默认中文，稳定检索字段保留英文 token
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
from collections.abc import Iterable
from typing import Any

_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_request_id", default="-"
)
_TASK_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_task_id", default="-"
)
_USER_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_user_id", default="-"
)
_AGENT_TYPE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_agent_type", default="-"
)
_DOMAIN_MODE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_domain_mode", default="-"
)
_RUN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "local_log_run_id", default="-"
)

_LLM_FULL_LOGGING_ENABLED = False


def configure_local_logging(*, debug: bool = False) -> None:
    """配置本地日志辅助开关。

    `debug=True` 时默认允许记录完整 LLM prompt/response；
    也可以通过环境变量 `XAGENT_LLM_LOG_FULL_CONTENT` 强制打开。
    """

    global _LLM_FULL_LOGGING_ENABLED
    env_value = os.getenv("XAGENT_LLM_LOG_FULL_CONTENT", "").strip().lower()
    _LLM_FULL_LOGGING_ENABLED = debug or env_value in {"1", "true", "yes", "on"}


def should_log_full_llm_content() -> bool:
    """返回当前是否允许完整记录 LLM 输入输出。"""

    return _LLM_FULL_LOGGING_ENABLED


def bind_log_context(
    *,
    request_id: Any | None = None,
    task_id: Any | None = None,
    user_id: Any | None = None,
    agent_type: Any | None = None,
    domain_mode: Any | None = None,
    run_id: Any | None = None,
) -> dict[str, contextvars.Token[str]]:
    """绑定本次执行链路的日志上下文并返回 token。

    调用方应在 `finally` 中使用 `reset_log_context` 还原，避免上下文泄漏到其他请求。
    """

    tokens: dict[str, contextvars.Token[str]] = {}
    if request_id is not None:
        tokens["request_id"] = _REQUEST_ID.set(str(request_id))
    if task_id is not None:
        tokens["task_id"] = _TASK_ID.set(str(task_id))
    if user_id is not None:
        tokens["user_id"] = _USER_ID.set(str(user_id))
    if agent_type is not None:
        tokens["agent_type"] = _AGENT_TYPE.set(str(agent_type))
    if domain_mode is not None:
        tokens["domain_mode"] = _DOMAIN_MODE.set(str(domain_mode))
    if run_id is not None:
        tokens["run_id"] = _RUN_ID.set(str(run_id))
    return tokens


def reset_log_context(tokens: dict[str, contextvars.Token[str]]) -> None:
    """恢复之前的日志上下文。"""

    if "request_id" in tokens:
        _REQUEST_ID.reset(tokens["request_id"])
    if "task_id" in tokens:
        _TASK_ID.reset(tokens["task_id"])
    if "user_id" in tokens:
        _USER_ID.reset(tokens["user_id"])
    if "agent_type" in tokens:
        _AGENT_TYPE.reset(tokens["agent_type"])
    if "domain_mode" in tokens:
        _DOMAIN_MODE.reset(tokens["domain_mode"])
    if "run_id" in tokens:
        _RUN_ID.reset(tokens["run_id"])


def get_log_context() -> dict[str, str]:
    """返回当前上下文，供 formatter 或埋点直接复用。"""

    return {
        "request_id": _REQUEST_ID.get(),
        "task_id": _TASK_ID.get(),
        "user_id": _USER_ID.get(),
        "agent_type": _AGENT_TYPE.get(),
        "domain_mode": _DOMAIN_MODE.get(),
        "run_id": _RUN_ID.get(),
    }


class ContextFilter(logging.Filter):
    """把上下文注入到所有日志记录中。"""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_log_context()
        record.request_id = context["request_id"]
        record.task_id = context["task_id"]
        record.user_id = context["user_id"]
        record.agent_type = context["agent_type"]
        record.domain_mode = context["domain_mode"]
        record.run_id = context["run_id"]
        return True


class HealthAccessFilter(logging.Filter):
    """过滤掉低价值健康检查访问日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "/health" not in message


class UvicornStartupNoiseFilter(logging.Filter):
    """过滤 uvicorn 重载场景下重复出现的低价值启动提示。"""

    _NOISE_KEYWORDS = (
        "Started server process",
        "Waiting for application startup",
        "Application startup complete",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(keyword in message for keyword in self._NOISE_KEYWORDS)


class UvicornProtocolNoiseFilter(logging.Filter):
    """过滤 WebSocket 协议级别的低价值调试日志。

    这类日志主要来自 uvicorn / websockets 在 DEBUG 级别下输出的协议细节，
    例如 101 握手头、ping/pong、连接状态切换等。它们会大量刷屏，但对
    绝大多数生产排障没有帮助，反而淹没真正有价值的业务日志。
    """

    _NOISE_PATTERNS = (
        "HTTP/1.1 101 Switching Protocols",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Accept:",
        "Sec-WebSocket-Extensions:",
        "connection open",
        "connection closed",
        "connection is OPEN",
        "connection is CLOSING",
        "connection is CLOSED",
        "sending keepalive ping",
        "received keepalive pong",
        "> PING ",
        "< PONG ",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(pattern in message for pattern in self._NOISE_PATTERNS)


def summarize_text(value: Any, *, limit: int = 200) -> str:
    """把任意值压缩成适合日志查看的单行摘要。"""

    if value is None:
        return "-"

    if isinstance(value, str):
        text = value.replace("\r", " ").replace("\n", " ").strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            text = str(value)

    text = " ".join(text.split())
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text or "-"


def summarize_messages(messages: Iterable[dict[str, Any]], *, limit: int = 240) -> str:
    """提炼消息列表摘要，便于记录到 `llm.log`。"""

    parts: list[str] = []
    for message in list(messages)[-4:]:
        role = str(message.get("role") or "unknown")
        content = summarize_text(message.get("content"), limit=80)
        parts.append(f"{role}:{content}")
    joined = " | ".join(parts)
    return summarize_text(joined, limit=limit)


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = summarize_text(value, limit=240)
    if any(char.isspace() for char in text) or any(char in text for char in {'"', "="}):
        escaped = text.replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _build_event_message(
    *,
    event: str,
    msg: str,
    fields: dict[str, Any] | None = None,
) -> str:
    segments = [f"event={event}", f'msg="{msg}"']
    for key, value in (fields or {}).items():
        if value is None:
            continue
        segments.append(f"{key}={_format_value(value)}")
    return " ".join(segments)


def log_decision(
    logger: logging.Logger,
    *,
    event: str,
    msg: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """记录关键决策类日志。"""

    logger.log(level, _build_event_message(event=event, msg=msg, fields=fields))


def log_dataflow(
    logger: logging.Logger,
    *,
    event: str,
    msg: str,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """记录数据流转类日志。"""

    logger.log(level, _build_event_message(event=event, msg=msg, fields=fields))


def log_llm_call_started(
    *,
    model: str,
    call_type: str,
    input_summary: str,
    logger_name: str = "xagent.llm",
    **fields: Any,
) -> float:
    """记录 LLM 调用开始事件，并返回开始时间。"""

    started_at = time.perf_counter()
    llm_logger = logging.getLogger(logger_name)
    payload = {
        "model": model,
        "call_type": call_type,
        "input_summary": input_summary,
        **fields,
    }
    llm_logger.info(
        _build_event_message(
            event="llm_call_started",
            msg="开始调用语言模型",
            fields=payload,
        )
    )
    return started_at


def log_llm_call_finished(
    *,
    started_at: float,
    model: str,
    call_type: str,
    input_summary: str,
    output_summary: str,
    usage: dict[str, Any] | None = None,
    logger_name: str = "xagent.llm",
    **fields: Any,
) -> None:
    """记录 LLM 调用完成事件。"""

    llm_logger = logging.getLogger(logger_name)
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    payload = {
        "model": model,
        "call_type": call_type,
        "latency_ms": latency_ms,
        "output_summary": output_summary,
        **(usage or {}),
        **fields,
    }
    llm_logger.info(
        _build_event_message(
            event="llm_call_finished",
            msg="语言模型调用完成",
            fields=payload,
        )
    )


def log_llm_call_failed(
    *,
    started_at: float,
    model: str,
    call_type: str,
    input_summary: str,
    error: Exception,
    logger_name: str = "xagent.llm",
    **fields: Any,
) -> None:
    """记录 LLM 调用失败事件。"""

    llm_logger = logging.getLogger(logger_name)
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    payload = {
        "model": model,
        "call_type": call_type,
        "latency_ms": latency_ms,
        "input_summary": input_summary,
        "error_type": type(error).__name__,
        "reason": summarize_text(str(error), limit=300),
        **fields,
    }
    llm_logger.error(
        _build_event_message(
            event="llm_call_failed",
            msg="语言模型调用失败",
            fields=payload,
        )
    )
