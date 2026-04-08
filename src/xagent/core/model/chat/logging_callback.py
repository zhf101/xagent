"""LLM 独立日志工具。

职责边界：
- 为平台内的 LLM 调用提供独立日志文件，避免和常规应用日志混在一起；
- 给 OpenAI 主执行链路与 LangChain 兼容链路提供统一的请求/响应摘要格式；
- 默认只记录排障所需的摘要信息，避免把完整上下文和敏感信息原样落盘。
"""

from __future__ import annotations

import json
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from ...utils.security import redact_sensitive_text

LLM_LOGGER_NAME = "xagent.llm"
_LLM_LOGGING_CONFIGURED = False
_LLM_HTTP_LOGGING_CONFIGURED = False


def _get_default_llm_log_file() -> str:
    """返回项目内固定的 LLM 日志文件路径。

    这里刻意把默认路径收口到仓库根目录下的 `logs/llm_requests.log`，
    原因是：
    - 纯文件名会受启动 cwd 影响，`uvicorn`、脚本、测试三种启动方式可能把日志写到不同目录
    - 用户排障时最怕“日志功能开了，但不知道文件到底落在哪”

    因此默认值直接返回绝对路径，保证无论从哪里启动，日志都落到同一个位置。
    """
    repo_root = Path(__file__).resolve().parents[5]
    return str(repo_root / "logs" / "llm_requests.log")


def is_llm_logging_enabled() -> bool:
    """判断是否启用独立 LLM 日志。"""
    return os.getenv("ENABLE_LLM_LOGGING", "false").lower() == "true"


def _truncate_text(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    cleaned = redact_sensitive_text(" ".join(str(text).split()))
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[:limit]}...(truncated)"


def _json_safe(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _summarize_message_content(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"type": "text", "preview": _truncate_text(content)}
    if isinstance(content, list):
        items: list[dict[str, Any]] = []
        for item in content[:5]:
            if isinstance(item, dict):
                item_type = item.get("type", "unknown")
                preview = ""
                if item_type == "text":
                    preview = _truncate_text(str(item.get("text", "")))
                elif item_type == "image_url":
                    preview = _truncate_text(str(item.get("image_url", "")), 160)
                items.append({"type": item_type, "preview": preview})
            else:
                items.append(
                    {"type": type(item).__name__, "preview": _truncate_text(str(item))}
                )
        return {
            "type": "multimodal",
            "items": items,
            "item_count": len(content),
        }
    return {"type": type(content).__name__, "preview": _truncate_text(str(content))}


def summarize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 prompt/messages 压缩成适合排障的摘要。"""
    summary: list[dict[str, Any]] = []
    for message in messages[:20]:
        summary.append(
            {
                "role": message.get("role", "unknown"),
                "name": message.get("name"),
                "content": _summarize_message_content(message.get("content")),
            }
        )
    if len(messages) > 20:
        summary.append(
            {
                "role": "system",
                "content": {
                    "type": "meta",
                    "preview": f"... {len(messages) - 20} more messages",
                },
            }
        )
    return summary


def summarize_tools(tools: list[dict[str, Any]] | None) -> list[str]:
    """仅记录工具名，避免把完整 schema 重复写入日志。"""
    if not tools:
        return []
    tool_names: list[str] = []
    for tool_def in tools[:50]:
        if not isinstance(tool_def, dict):
            tool_names.append(type(tool_def).__name__)
            continue
        function_def = tool_def.get("function") or {}
        tool_names.append(
            str(
                function_def.get("name")
                or tool_def.get("name")
                or tool_def.get("type")
                or "unknown"
            )
        )
    return tool_names


def setup_llm_logging(
    log_file: str | None = None,
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """配置独立 LLM 日志文件。"""
    global _LLM_LOGGING_CONFIGURED

    llm_logger = logging.getLogger(LLM_LOGGER_NAME)
    if _LLM_LOGGING_CONFIGURED:
        return llm_logger

    resolved_log_file = log_file or _get_default_llm_log_file()
    log_path = Path(resolved_log_file)
    # 独立日志的主要价值是“出问题时一定能落盘”。
    # 因此这里在初始化阶段主动补齐父目录，避免目录不存在导致 handler 创建失败。
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
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

    llm_logger.setLevel(log_level)
    llm_logger.addHandler(file_handler)
    llm_logger.propagate = False
    llm_logger.info("LLM 独立日志已启用: %s", str(log_path))

    _LLM_LOGGING_CONFIGURED = True
    return llm_logger


def setup_llm_logging_from_env() -> bool:
    """根据环境变量启用 LLM 独立日志。"""
    global _LLM_HTTP_LOGGING_CONFIGURED

    if not is_llm_logging_enabled():
        return False

    llm_logger = setup_llm_logging(
        log_file=os.getenv("LLM_LOG_FILE") or _get_default_llm_log_file(),
        log_level=logging.INFO,
        max_bytes=int(os.getenv("LLM_LOG_MAX_BYTES", str(10 * 1024 * 1024))),
        backup_count=int(os.getenv("LLM_LOG_BACKUP_COUNT", "5")),
    )

    enable_http_logging = (
        os.getenv("ENABLE_LLM_HTTP_LOGGING", "false").lower() == "true"
    )
    if enable_http_logging and not _LLM_HTTP_LOGGING_CONFIGURED:
        for logger_name in ("httpx", "httpcore", "openai", "langchain"):
            target = logging.getLogger(logger_name)
            target.setLevel(logging.DEBUG)
            for handler in llm_logger.handlers:
                target.addHandler(handler)
            target.propagate = False
        llm_logger.info("LLM 底层 HTTP 日志已启用")
        _LLM_HTTP_LOGGING_CONFIGURED = True

    return True


def get_llm_logger() -> logging.Logger:
    """获取 LLM logger，并在需要时做懒初始化。"""
    setup_llm_logging_from_env()
    return logging.getLogger(LLM_LOGGER_NAME)


def log_llm_request_start(
    *,
    call_type: str,
    model_name: str,
    base_url: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    response_format: dict[str, Any] | None,
    thinking: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> float:
    """记录一次 LLM 调用开始。"""
    if not is_llm_logging_enabled():
        return time.time()

    logger = get_llm_logger()
    logger.info(
        "[LLM %s] request=%s",
        call_type,
        _json_safe(
            {
                "model": model_name,
                "base_url": _truncate_text(base_url, 160),
                "message_count": len(messages),
                "messages": summarize_messages(messages),
                "tool_count": len(tools or []),
                "tools": summarize_tools(tools),
                "tool_choice": tool_choice,
                "response_format": response_format,
                "thinking": thinking,
                "extra": extra or {},
            }
        ),
    )
    return time.time()


def log_llm_request_end(
    *,
    call_type: str,
    model_name: str,
    started_at: float,
    result: dict[str, Any],
    usage: Any = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """记录一次 LLM 调用结束。"""
    if not is_llm_logging_enabled():
        return

    elapsed_ms = round((time.time() - started_at) * 1000, 2)
    payload: dict[str, Any] = {
        "model": model_name,
        "elapsed_ms": elapsed_ms,
        "result_type": result.get("type"),
        "extra": extra or {},
    }
    if result.get("type") == "text":
        payload["content_preview"] = _truncate_text(str(result.get("content", "")), 800)
    if result.get("type") == "tool_call":
        payload["tool_calls"] = [
            {
                "id": tool_call.get("id"),
                "type": tool_call.get("type"),
                "name": tool_call.get("function", {}).get("name"),
                "arguments_preview": _truncate_text(
                    str(tool_call.get("function", {}).get("arguments", "")),
                    400,
                ),
            }
            for tool_call in result.get("tool_calls", [])
        ]
    if usage is not None:
        if isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        else:
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            total_tokens = getattr(usage, "total_tokens", None)
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    get_llm_logger().info("[LLM %s] response=%s", call_type, _json_safe(payload))


def log_llm_request_error(
    *,
    call_type: str,
    model_name: str,
    started_at: float,
    error: Exception,
    extra: dict[str, Any] | None = None,
) -> None:
    """记录一次 LLM 调用失败。"""
    if not is_llm_logging_enabled():
        return

    elapsed_ms = round((time.time() - started_at) * 1000, 2)
    get_llm_logger().error(
        "[LLM %s] error=%s",
        call_type,
        _json_safe(
            {
                "model": model_name,
                "elapsed_ms": elapsed_ms,
                "error_type": type(error).__name__,
                "error": _truncate_text(str(error), 1200),
                "extra": extra or {},
            }
        ),
    )


class LLMRequestResponseLogger(BaseCallbackHandler):
    """LangChain 兼容链路的请求/响应摘要日志。"""

    def __init__(self, log_level: int = logging.INFO):
        super().__init__()
        self.log_level = log_level
        self._call_counter = 0
        self._call_started_at: dict[int, float] = {}

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        self._call_counter += 1
        call_id = self._call_counter
        self._call_started_at[call_id] = time.time()
        logger = get_llm_logger()
        logger.log(
            self.log_level,
            "[LangChain LLM start] %s",
            _json_safe(
                {
                    "call_id": call_id,
                    "serialized": serialized,
                    "prompt_count": len(prompts),
                    "prompts": [_truncate_text(prompt, 800) for prompt in prompts[:10]],
                    "invocation_params": kwargs.get("invocation_params"),
                }
            ),
        )

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        logger = get_llm_logger()
        call_id = self._call_counter
        started_at = self._call_started_at.pop(call_id, time.time())
        generations: list[dict[str, Any]] = []
        for group in response.generations[:5]:
            for generation in group[:5]:
                text = getattr(generation, "text", "") or ""
                generations.append({"text_preview": _truncate_text(text, 800)})

        logger.log(
            self.log_level,
            "[LangChain LLM end] %s",
            _json_safe(
                {
                    "call_id": call_id,
                    "elapsed_ms": round((time.time() - started_at) * 1000, 2),
                    "generations": generations,
                    "llm_output": response.llm_output,
                }
            ),
        )

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        call_id = self._call_counter
        started_at = self._call_started_at.pop(call_id, time.time())
        get_llm_logger().error(
            "[LangChain LLM error] %s",
            _json_safe(
                {
                    "call_id": call_id,
                    "elapsed_ms": round((time.time() - started_at) * 1000, 2),
                    "error_type": type(error).__name__,
                    "error": _truncate_text(str(error), 1200),
                }
            ),
        )


def enable_llm_request_logging(
    log_level: int = logging.INFO,
) -> LLMRequestResponseLogger:
    """创建 LangChain 回调并确保独立日志已初始化。"""
    setup_llm_logging_from_env()
    return LLMRequestResponseLogger(log_level=log_level)
