"""
`Probe Execution`（探测执行）模块。

Probe 的目标不是完成真实业务动作，而是用最小副作用验证：
- 资源能不能通
- 参数能不能过
- 返回结构是不是符合预期
"""

from __future__ import annotations

from typing import Any


class ProbeExecutor:
    """
    `ProbeExecutor`（探测执行器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：正式执行前的低副作用验证器

    主要职责：
    - 执行 `probe`（探测）模式动作。
    - 用最小副作用验证资源连通性、参数完整性、返回结构与权限可用性。
    - 为后续是否允许正式 `execute`（正式执行）提供证据。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个探测契约。

        注意这里的执行目标是“验证”，不是“完成业务结果”。
        """
        raise NotImplementedError("ProbeExecutor.execute 尚未实现")
