"""多数据库接入的统一导出入口。

这层模块的职责非常单纯：
- 提供数据库类型标准化能力
- 提供连接表单 / URL 编解码能力
- 提供 adapter 工厂

它不承担任何业务主循环控制职责，只是 Resource / Web 基础设施能力层。
"""

from .connection_form import (
    build_connection_url,
    get_connection_form_definition,
    mask_connection_url,
    parse_connection_url,
)
from .profiles import DATABASE_PROFILES, get_database_profile, list_database_profiles
from .types import (
    DATABASE_TYPE_ALIASES,
    DATABASE_TYPE_CANONICAL_VALUES,
    DatabaseType,
    normalize_database_type,
    try_normalize_database_type,
)

__all__ = [
    "DATABASE_TYPE_ALIASES",
    "DATABASE_TYPE_CANONICAL_VALUES",
    "DATABASE_PROFILES",
    "DatabaseType",
    "build_connection_url",
    "get_database_profile",
    "get_connection_form_definition",
    "list_database_profiles",
    "mask_connection_url",
    "normalize_database_type",
    "parse_connection_url",
    "try_normalize_database_type",
]
