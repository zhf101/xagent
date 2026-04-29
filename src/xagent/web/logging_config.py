"""统一日志配置 - xagent web应用

【Bug修复】日志目录不存在时自动创建
- 问题: Python的logging.FileHandler不会自动创建不存在的目录
- 原代码: 硬编码'/applog/xagent/app.log',Windows下会报FileNotFoundError
- 修复方案:
  1. 使用pathlib.Path.mkdir(parents=True)自动创建多级目录
  2. 支持XAGENT_LOG_FILE环境变量自定义日志路径
  3. 创建失败时优雅降级为仅控制台日志,不阻断应用启动
  4. 添加encoding='utf-8'确保跨平台编码一致性

【使用方法】
# 使用默认路径(/applog/xagent/app.log 或 D:\\applog\\xagent\\app.log)
python run_web_debug.py

# 自定义日志路径
export XAGENT_LOG_FILE="/tmp/myapp.log"  # Linux/Mac
set XAGENT_LOG_FILE=D:\\logs\\xagent.log   # Windows

# 仅控制台日志(不写文件)
export XAGENT_LOG_FILE=""
"""

import logging
import os
from logging.config import dictConfig
from pathlib import Path
from typing import Literal, cast

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


_is_applied = False


def setup_logging(level: LogLevel | None = None, force: bool = False) -> None:
    """Configure logging for the entire application.

    Args:
        level: Log level. If None, reads from XAGENT_LOG_LEVEL env var,
               defaults to "INFO" if env var is not set or invalid.
        force: If True, reconfigure logging even if already applied.
    """
    global _is_applied
    if _is_applied and not force:
        return
    
    # 日志文件路径配置 - 支持跨平台自动创建目录
    # 优先级: XAGENT_LOG_FILE 环境变量 > 默认路径
    log_file = os.getenv("XAGENT_LOG_FILE", "/applog/xagent/app.log")
    
    # 自动创建日志文件所在目录（如果不存在）
    log_dir = Path(log_file).parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # 如果创建失败（如权限问题），降级为仅控制台日志
        print(f"Warning: Cannot create log directory '{log_dir}': {e}")
        print("Falling back to console-only logging")
        log_file = None
    
    # 如果未提供日志级别，从环境变量读取
    if level is None:
        level = cast(LogLevel, os.getenv("XAGENT_LOG_LEVEL", "INFO").upper())
    else:
        level = cast(LogLevel, level.upper())
    # 验证并回退到 INFO（如果无效）
    original_level = level
    if invalid_level := level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = "INFO"
    
    # 构建日志配置
    handlers_config = {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    }
    
    # 只有在日志文件路径有效时才添加文件 handler
    if log_file:
        handlers_config["file"] = {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": log_file,
            "encoding": "utf-8",  # 确保跨平台编码一致性
        }
        root_handlers = ["default", "file"]
    else:
        root_handlers = ["default"]
    
    # 应用日志配置
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": handlers_config,
            "loggers": {
                "aiohttp": {"level": "WARNING"},
                "sqlalchemy": {"level": "WARNING"},
                "urllib3": {"level": "WARNING"},
                "uvicorn.access": {"level": "WARNING"},
                "uvicorn.error": {"level": "INFO"},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "xagent": {"level": level},
            },
            "root": {
                "level": level,
                "handlers": root_handlers
            },
        }
    )

    if invalid_level:
        logging.warning(
            "Invalid log level '%r', falling back to 'INFO'", original_level
        )

    _is_applied = True
