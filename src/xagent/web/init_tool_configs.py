"""Initialize tool configurations in database."""

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from .models.database import get_db
from .models.tool_config import ToolConfig

logger = logging.getLogger(__name__)


def get_default_tool_configs() -> list[Dict[str, Any]]:
    """获取默认工具配置"""
    return [
        {
            "tool_name": "python_executor",
            "tool_type": "builtin",
            "category": "development",
            "display_name": "Python 代码执行器",
            "description": "执行 Python 代码，支持数据分析和计算任务",
            "enabled": True,
            "config": {"working_dir": "/workspace/output"},
            "dependencies": [],
        },
        {
            "tool_name": "bash",
            "tool_type": "builtin",
            "category": "development",
            "display_name": "Bash 命令执行器",
            "description": "执行 Bash 命令，进行系统操作和文件管理",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "query_http_resource",
            "tool_type": "builtin",
            "category": "basic",
            "display_name": "HTTP 接口查询",
            "description": "查询存量造数场景 HTTP API 接口，获取接口详细信息判断是否可用于当前任务",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "execute_http_resource",
            "tool_type": "builtin",
            "category": "basic",
            "display_name": "HTTP 接口执行",
            "description": "执行存量造数 HTTP API 接口调用，resource_key 从 query_http_resource 结果获取",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "query_vanna_sql_asset",
            "tool_type": "builtin",
            "category": "database",
            "display_name": "SQL 资产查询",
            "description": "通过自然语言搜索匹配的 SQL 资产，返回参数绑定预览和编译后的 SQL",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "execute_vanna_sql_asset",
            "tool_type": "builtin",
            "category": "database",
            "display_name": "SQL 资产执行",
            "description": "执行指定的 SQL 资产，通过配置的数据源适配器链连接目标数据库",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "sql_query",
            "tool_type": "builtin",
            "category": "database",
            "display_name": "SQL 查询",
            "description": "对当前用户已配置的数据源执行 SQL 查询",
            "enabled": True,
            "requires_configuration": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "fetch_webpage",
            "tool_type": "builtin",
            "category": "search",
            "display_name": "网页内容获取",
            "description": "获取网页内容，支持文本提取和解析",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "calculator",
            "tool_type": "builtin",
            "category": "development",
            "display_name": "计算器",
            "description": "进行数学计算和表达式求值",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "read_file",
            "tool_type": "file",
            "category": "file_operations",
            "display_name": "文件读取",
            "description": "读取文件内容，支持多种文件格式",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "write_file",
            "tool_type": "file",
            "category": "file_operations",
            "display_name": "文件写入",
            "description": "写入文件内容，支持多种文件格式",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "list_directory",
            "tool_type": "file",
            "category": "file_operations",
            "display_name": "目录列表",
            "description": "列出目录内容，支持文件过滤和排序",
            "enabled": True,
            "config": {},
            "dependencies": [],
        },
        {
            "tool_name": "vision_tool",
            "tool_type": "vision",
            "category": "ai_tools",
            "display_name": "视觉分析工具",
            "description": "分析图像内容，支持图像识别和理解",
            "enabled": True,
            "config": {},
            "dependencies": ["vision_model"],
        },
        {
            "tool_name": "image_generation",
            "tool_type": "image",
            "category": "ai_tools",
            "display_name": "图像生成",
            "description": "根据文本描述生成图像",
            "enabled": True,
            "config": {},
            "dependencies": ["image_model"],
        },
    ]


def init_tool_configs(db: Session) -> None:
    """初始化数据库中的工具配置"""
    logger.info("Initializing tool configurations...")

    default_configs = get_default_tool_configs()

    for config_data in default_configs:
        # 检查工具配置是否已存在
        existing = (
            db.query(ToolConfig)
            .filter(ToolConfig.tool_name == config_data["tool_name"])
            .first()
        )

        if existing:
            logger.info(
                f"Tool config '{config_data['tool_name']}' already exists, skipping..."
            )
            continue

        # 创建新工具配置
        tool_config = ToolConfig(**config_data)
        db.add(tool_config)
        logger.info(f"Added tool config: {config_data['tool_name']}")

    db.commit()
    logger.info("Tool configurations initialized successfully.")


def main() -> None:
    """初始化工具配置的主函数"""
    logging.basicConfig(level=logging.INFO)

    db = next(get_db())
    try:
        init_tool_configs(db)
        print("Tool configurations initialized successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize tool configurations: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
