"""
`Supervision Channel`（人工监督通道）桥接模块。

这一层对应你设计里“需要人工审批、人工放行、人工驳回”的分支。
它和用户交互通道的差别在于：这里的参与者不是普通终端用户，
而是具备治理权限的审核人或运营人。
"""

from __future__ import annotations

from typing import Any


class SupervisionBridge:
    """
    `SupervisionBridge`（人工监督桥接器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`Human in Loop Channel`（人工在环通道）
    - 在你的设计里：审批等待态与审批回流入口

    主要职责：
    - 创建人工审批等待态，生成 `Approval Ticket`（审批工单）。
    - 将审批请求发送给外部审核系统、控制台或审批 UI。
    - 回收审批结论，并转为统一的 `SupervisionObservation`
      （人工监督观察结果）。

    明确边界：
    - 不负责决定是否需要审批；是否触发审批由顶层 Agent 或 Guard 决定。
    - 不负责执行资源动作；审批通过后仍需进入 runtime。
    """

    async def open_approval(self, decision: Any) -> Any:
        """
        创建 `Approval Ticket`（审批工单）。

        这个工单会携带审批原因、风险摘要、待执行动作概要等审计所需信息。
        """
        raise NotImplementedError("SupervisionBridge.open_approval 尚未实现")

    async def consume_decision(self, approval_result: Any) -> Any:
        """
        消费审批结果，并转为统一 `SupervisionObservation`（人工监督观察结果）。

        它的输出会回到顶层主脑或 continuation 恢复逻辑，驱动后续流程继续。
        """
        raise NotImplementedError("SupervisionBridge.consume_decision 尚未实现")
