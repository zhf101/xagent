"""
技能可用性检查服务。

这里的职责很克制：
- 只判断运行环境是否满足 skill 的最低使用条件
- 不表达权限，不表达审批，不表达最终是否应该由主脑选中
"""

from __future__ import annotations

import os
import shutil

from .catalog_models import SkillAvailability, SkillDescriptor


class SkillAvailabilityService:
    """负责技能的环境可用性检查。"""

    def evaluate(self, descriptor: SkillDescriptor) -> SkillAvailability:
        """
        对单个技能做可用性检查。

        输入语义：
        - `descriptor.metadata.requires_tools` 表达依赖的工具能力
        - `descriptor.metadata.requires_env` 表达必须存在的环境变量

        输出语义：
        - 只回答“当前环境能不能用”
        - 不回答“当前业务应不应该用”
        """

        missing_tools = [
            tool
            for tool in descriptor.metadata.requires_tools
            if shutil.which(tool) is None
        ]
        missing_env = [
            env_key
            for env_key in descriptor.metadata.requires_env
            if not os.getenv(env_key)
        ]

        reasons: list[str] = []
        if missing_tools:
            reasons.append(f"缺少依赖工具: {', '.join(missing_tools)}")
        if missing_env:
            reasons.append(f"缺少环境变量: {', '.join(missing_env)}")

        return SkillAvailability(
            available=not missing_tools and not missing_env,
            missing_tools=missing_tools,
            missing_env=missing_env,
            reasons=reasons,
        )
