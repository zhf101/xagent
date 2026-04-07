"""Vanna 模块异常定义。"""


class VannaError(Exception):
    """Vanna 基础异常。"""


class VannaDatasourceNotFoundError(VannaError):
    """找不到指定数据源。"""


class VannaKnowledgeBaseNotFoundError(VannaError):
    """找不到指定知识库。"""


class VannaTrainingEntryNotFoundError(VannaError):
    """找不到指定训练条目。"""


class VannaGenerationError(VannaError):
    """SQL 生成失败。"""


class VannaExecutionError(VannaError):
    """SQL 执行失败。"""

