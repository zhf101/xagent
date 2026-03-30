"""
`GuardService`（护栏服务）入口模块。

这里对应你设计中的执行前统一裁决口。
所有 `execution_action`（执行动作）在真正进入 runtime 之前，
都应该先在这里完成合法性、风险、审批、路由方式等判断。
"""

from __future__ import annotations

from typing import Any


class GuardService:
    """
    `GuardService`（护栏服务）。

    所属分层：
    - 代码分层：`guard`
    - 需求分层：`Guard / Routing Plane`（护栏 / 路由平面）
    - 在你的设计里：执行前总裁决入口

    主要职责：
    - 校验 `execution_action`（执行动作）是否合法、是否属于受控资源动作。
    - 判断参数是否齐备，是否满足最小执行前提。
    - 结合策略判断风险等级、审批要求、是否只能 probe。
    - 产出 `GuardVerdict`（护栏裁决结果），为后续 Runtime 路由提供标准输入。

    明确边界：
    - 不负责决定业务上“该不该做这件事”；那是主脑的职责。
    - 不负责真正执行动作；真正执行属于 runtime。
    """

    async def evaluate(self, action: Any) -> Any:
        """
        对执行动作进行护栏裁决。

        未来会综合：
        - `ReadinessChecker`（就绪性检查器）
        - `RiskPolicy`（风险策略）
        - `ApprovalPolicy`（审批策略）

        最终输出标准化的 `GuardVerdict`（护栏裁决结果）。
        """
        raise NotImplementedError("GuardService.evaluate 尚未实现")
