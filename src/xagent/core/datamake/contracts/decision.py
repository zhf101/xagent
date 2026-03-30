"""
`Decision Contracts`（决策契约）模块。

这里放的是顶层主脑输出契约。
它们决定了主脑和下游层之间到底用什么结构说话。
"""


class NextActionDecisionContract:
    """
    `NextActionDecisionContract`（下一动作决策契约）占位类。

    所属分层：
    - 代码分层：`contracts`
    - 需求分层：`Agent Control Plane`（Agent 控制平面）输出契约
    - 在你的设计里：主脑单轮输出的核心协议

    主要职责：
    - 统一约束顶层 Agent 每一轮的结构化决策输出。
    - 后续承载动作模式、目标资源、参数、用户可见信息、终止语义等字段。
    """


class UserVisiblePayloadContract:
    """
    `UserVisiblePayloadContract`（用户可见载荷契约）占位类。

    主要职责：
    - 约束 `user_visible`（用户可见载荷）的外部展示结构。
    - 作为内部决策与前端展示协议之间的明确边界。
    """
