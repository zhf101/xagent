"""xagent Web 本地日志配置。"""

from __future__ import annotations

import os
from logging.config import dictConfig
from pathlib import Path
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _ensure_log_dir(log_dir: str) -> str:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def build_logging_config(level: LogLevel = "INFO", *, debug: bool = False) -> dict:
    """构建可复用的 logging dictConfig。

    这份配置既给当前进程直接 `dictConfig` 使用，也给 uvicorn 的 reload
    子进程使用，避免父进程和工作进程日志行为不一致。
    """
    log_dir = _ensure_log_dir(os.getenv("XAGENT_LOG_DIR", "logs"))
    llm_level = "DEBUG" if debug else level
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {
                "()": "xagent.core.observability.local_logging.ContextFilter"
            },
            "drop_health_access": {
                "()": "xagent.core.observability.local_logging.HealthAccessFilter"
            },
            "drop_uvicorn_startup_noise": {
                "()": "xagent.core.observability.local_logging.UvicornStartupNoiseFilter"
            },
            "drop_uvicorn_protocol_noise": {
                "()": "xagent.core.observability.local_logging.UvicornProtocolNoiseFilter"
            },
        },
        "formatters": {
            "app": {
                "format": (
                    "%(asctime)s %(levelname)-8s %(name)s "
                    "request_id=%(request_id)s task_id=%(task_id)s user_id=%(user_id)s "
                    "agent_type=%(agent_type)s domain_mode=%(domain_mode)s run_id=%(run_id)s "
                    "- %(message)s"
                ),
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "format": "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "app",
                "filters": ["context"],
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "app",
                "filters": ["context"],
                "filename": str(Path(log_dir) / "app.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "access_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "access",
                "filters": ["drop_health_access"],
                "filename": str(Path(log_dir) / "access.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "llm_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "app",
                "filters": ["context"],
                "filename": str(Path(log_dir) / "llm.log"),
                "maxBytes": 10 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
            "loggers": {
                "aiohttp": {"level": "WARNING"},
                "sqlalchemy": {"level": "WARNING"},
                "urllib3": {"level": "WARNING"},
                "xagent.core.agent.trace": {"level": "WARNING"},
                "xagent.core.agent.pattern.dag_plan_execute.plan_generator": {"level": "WARNING"},
                "xagent.core.agent.pattern.dag_plan_execute.result_analyzer": {"level": "WARNING"},
                "watchfiles": {"level": "WARNING"},
                "watchfiles.main": {"level": "WARNING"},
                "uvicorn.access": {
                "level": "INFO",
                "handlers": ["access_file"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["console", "app_file"],
                "filters": [
                    "drop_uvicorn_startup_noise",
                    "drop_uvicorn_protocol_noise",
                ],
                "propagate": False,
            },
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
            "xagent.llm": {
                "level": llm_level,
                "handlers": ["console", "llm_file"],
                "propagate": False,
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "app_file"],
        },
    }


def setup_logging(level: LogLevel = "INFO", *, debug: bool = False) -> None:
    """配置应用日志。"""

    dictConfig(build_logging_config(level=level, debug=debug))
