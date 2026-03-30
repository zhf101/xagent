"""
`Action Execution`（正式动作执行）模块。

只有当动作已经通过护栏并满足正式执行条件时，才会进入这里。
这里会真正触达底层资源。
"""

from __future__ import annotations

from typing import Any


class ActionExecutor:
    """
    `ActionExecutor`（正式动作执行器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：真正落地资源调用的执行器

    主要职责：
    - 执行正式 `execute`（正式执行）模式动作。
    - 通过 `ResourceAdapter`（资源适配器）真正调用底层资源。
    - 统一封装执行结果、错误、重试上下文，避免上层感知资源细节。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个正式动作契约。

        输入是已编译好的运行时契约，而不是随意的资源调用参数。
        """
        raise NotImplementedError("ActionExecutor.execute 尚未实现")
