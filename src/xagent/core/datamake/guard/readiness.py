"""
`Readiness Check`（就绪性检查）模块。

这里负责回答一个很实际的问题：
“主脑想执行的动作，现在在技术层面到底能不能跑起来？”

例如资源是否注册、凭证是否存在、环境是否可达、动作签名是否满足等。
"""

from __future__ import annotations

from typing import Any


class ReadinessChecker:
    """
    `ReadinessChecker`（资源就绪性检查器）。

    所属分层：
    - 代码分层：`guard`
    - 需求分层：`Guard / Routing Plane`（护栏 / 路由平面）
    - 在你的设计里：执行前前置条件核验器

    主要职责：
    - 检查资源是否已经注册到 `ResourceCatalog`（资源目录）。
    - 检查环境、凭证、动作签名、依赖配置是否满足执行前提。
    - 将“业务上想执行”和“技术上可执行”明确拆开。
    """

    async def check(self, action: Any) -> Any:
        """
        检查动作所需资源是否就绪。

        未来这里的输出应是结构化就绪结果，而不是简单布尔值，
        以便上层明确知道到底缺了什么前置条件。
        """
        raise NotImplementedError("ReadinessChecker.check 尚未实现")
