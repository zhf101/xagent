"""
`Guard Contracts`（护栏契约）模块。

这里定义 guard 层输出给 runtime 或上游的标准裁决结构。
"""


class GuardVerdictContract:
    """
    `GuardVerdictContract`（护栏裁决契约）占位类。

    所属分层：
    - 代码分层：`contracts`
    - 需求分层：`Guard / Routing Plane`（护栏 / 路由平面）输出契约
    - 在你的设计里：执行前裁决结果的统一协议

    主要职责：
    - 表达 guard 对某个动作的最终判断。
    - 后续承载允许 / 拒绝、风险等级、审批要求、执行模式等字段。
    """
