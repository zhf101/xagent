"""
`Guard Policies`（护栏策略）集合模块。

这里放的不是流程编排器，而是可独立演进的裁决规则。
随着后续资源、环境、风控要求增加，这一层会逐步沉淀成可配置策略集。
"""

from __future__ import annotations

from typing import Any


class RiskPolicy:
    """
    `RiskPolicy`（风险评估策略）。

    所属分层：
    - 代码分层：`guard`
    - 需求分层：`Guard / Routing Plane`（护栏 / 路由平面）
    - 在你的设计里：风险分级规则器

    主要职责：
    - 基于资源动作、环境、数据范围、写入类型等信息给出风险等级。
    - 为是否审批、是否允许正式执行、是否需要额外审计提供依据。
    """

    def evaluate_risk(self, action: Any) -> Any:
        """
        评估动作风险。

        未来典型输出会是 low / medium / high 之类的结构化风险分级结果。
        """
        raise NotImplementedError("RiskPolicy.evaluate_risk 尚未实现")


class ApprovalPolicy:
    """
    `ApprovalPolicy`（审批要求策略）。

    所属分层：
    - 代码分层：`guard`
    - 需求分层：`Guard / Routing Plane`（护栏 / 路由平面）
    - 在你的设计里：放行条件判定器

    主要职责：
    - 判断动作是否需要人工确认或审批。
    - 判断当前动作是否只能先走 `probe`（探测执行）再走 `execute`
      （正式执行）。
    - 让审批触发条件从流程代码里剥离出来，便于后续治理调整。
    """

    def requires_approval(self, action: Any) -> bool:
        """
        判断当前动作是否需要审批。

        这里返回的只是审批要求判断，不代表审批工单的创建与发送。
        """
        raise NotImplementedError("ApprovalPolicy.requires_approval 尚未实现")
