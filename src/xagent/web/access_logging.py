"""Uvicorn 访问日志配置

将 uvicorn 的访问日志重定向到独立的 access.log 文件。
"""

import logging
import sys
from typing import Optional


def setup_access_logging(
    log_file: str = "access.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    disable_console: bool = True,
) -> None:
    """配置 uvicorn 访问日志
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别
        max_bytes: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件数量
        disable_console: 是否禁用控制台输出（避免污染应用日志）
    """
    from logging.handlers import RotatingFileHandler
    
    # 获取 uvicorn 的 access logger
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(log_level)
    
    # 清除现有的 handlers（避免重复日志）
    access_logger.handlers.clear()
    
    # 创建文件 handler（带日志轮转）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    
    # 创建格式化器（简洁格式）
    formatter = logging.Formatter(
        "%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    
    # 添加文件 handler
    access_logger.addHandler(file_handler)
    
    # 如果不禁用控制台，添加控制台 handler
    if not disable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        access_logger.addHandler(console_handler)
    
    # 防止日志传播到根 logger
    access_logger.propagate = False
    
    # 同时配置 uvicorn 的默认 logger
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.propagate = False
    
    # 记录配置信息
    app_logger = logging.getLogger("xagent.web")
    app_logger.info(f"访问日志已配置: {log_file}")
    if disable_console:
        app_logger.info("访问日志已从控制台移除，仅输出到文件")


def get_uvicorn_log_config(
    access_log_file: str = "access.log",
    disable_console: bool = True,
) -> dict:
    """获取 uvicorn 的日志配置字典
    
    用于传递给 uvicorn.run() 的 log_config 参数。
    
    Args:
        access_log_file: 访问日志文件路径
        disable_console: 是否禁用控制台输出
        
    Returns:
        uvicorn 日志配置字典
    """
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "format": "%(asctime)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access_file": {
                "formatter": "access",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": access_log_file,
                "maxBytes": 10 * 1024 * 1024,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["access_file"] if disable_console else ["access_file", "default"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
    
    return config
