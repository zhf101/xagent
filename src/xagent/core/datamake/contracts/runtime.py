"""
`Runtime Contracts`（运行时契约）模块。

这里定义 runtime 内部最关键的两类结构：
- 编译后的执行契约
- 运行完成后的执行结果
"""


class CompiledExecutionContract:
    """
    `CompiledExecutionContract`（编译后执行契约）占位类。

    所属分层：
    - 代码分层：`contracts`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）内部执行契约
    - 在你的设计里：动作编译后的标准执行协议

    主要职责：
    - 作为 runtime 执行器、资源适配器之间的统一输入结构。
    - 固化执行模式、目标资源、参数、恢复信息、幂等键等执行语义。
    """


class RuntimeResultContract:
    """
    `RuntimeResultContract`（运行时结果契约）占位类。

    主要职责：
    - 统一表达 runtime 层执行完成后的结果。
    - 后续承载成功、失败、暂停、恢复令牌、资源返回摘要等字段。
    """
