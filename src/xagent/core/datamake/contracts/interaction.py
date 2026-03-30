"""
`Interaction / Approval Contracts`（交互 / 审批契约）模块。

这里定义用户交互工单与审批工单的公共协议。
"""


class InteractionTicketContract:
    """
    `InteractionTicketContract`（用户交互工单契约）占位类。

    主要职责：
    - 约束用户补参、澄清、确认等等待态工单结构。
    - 作为前端交互通道与领域层之间的协议边界。
    """


class ApprovalTicketContract:
    """
    `ApprovalTicketContract`（审批工单契约）占位类。

    主要职责：
    - 约束人工审批请求的结构。
    - 后续承载审批理由、风险摘要、待执行动作概要等字段。
    """
