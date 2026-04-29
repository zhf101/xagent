"""
xagent 技能模块

本模块提供与 Claude Skills 格式兼容的技能管理系统。
技能是基于目录的模块，为任务规划提供知识和模板。
"""

from .manager import SkillManager
from .parser import SkillParser
from .selector import SkillSelector

__all__ = ["SkillManager", "SkillParser", "SkillSelector"]
