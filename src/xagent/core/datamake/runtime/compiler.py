"""
`ExecutionCompiler`（执行契约编译器）模块。

这个模块负责把“业务上想做什么”翻译成“运行时应该怎么执行”。
它是业务动作描述和底层执行细节之间的关键隔离层。
"""

from __future__ import annotations

from typing import Any


class ExecutionCompiler:
    """
    `ExecutionCompiler`（执行契约编译器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：动作到执行计划的编译器

    主要职责：
    - 把 `execution_action`（执行动作）编译成 Runtime 可执行的标准契约。
    - 隔离“业务动作描述”和“底层资源调用细节”，避免运行时直接消费松散字典。
    - 在契约里固化资源键、动作键、执行模式、幂等键、恢复信息等执行语义。
    """

    def compile(self, action: Any, verdict: Any) -> Any:
        """
        编译一个执行动作。

        这里未来会结合 Guard 裁决结果，把 action 固化成
        `CompiledExecutionContract`（编译后执行契约）。
        """
        raise NotImplementedError("ExecutionCompiler.compile 尚未实现")
