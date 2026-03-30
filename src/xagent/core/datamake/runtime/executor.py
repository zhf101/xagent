"""
`RuntimeExecutor`（运行时执行器）入口模块。

这里是 runtime 层的总入口。
在 Guard 已经给出 `GuardVerdict`（护栏裁决结果）之后，
这里负责把“允许执行”的动作真正推进下去。
"""

from __future__ import annotations

from typing import Any


class RuntimeExecutor:
    """
    `RuntimeExecutor`（运行时执行器）。

    所属分层：
    - 代码分层：`runtime`
    - 需求分层：`Runtime / Workflow Plane`（运行时 / 工作流平面）
    - 在你的设计里：执行层总协调入口

    主要职责：
    - 接收 `GuardVerdict`（护栏裁决结果）。
    - 调用 `ExecutionCompiler`（执行契约编译器）把动作转换成
      `CompiledExecutionContract`（编译后执行契约）。
    - 根据裁决与契约，路由到 `ProbeExecutor`（探测执行器）、
      `ActionExecutor`（正式动作执行器）或 `DagRuntimeAdapter`
      （DAG 运行时适配器）。
    - 统一处理 timeout、retry、idempotency、pause、resume 等工程问题。
    - 输出标准化的 `RuntimeResult`（运行时结果）或
      `ObservationEnvelope`（观察结果外壳）。

    明确边界：
    - 不负责重新决定业务目标。
    - 不直接暴露底层资源差异给顶层 Agent。
    """

    async def execute(self, verdict: Any) -> Any:
        """
        执行一个已经通过 Guard 的动作。

        输入语义：
        - `verdict`：护栏层给出的标准裁决结果，包含是否允许执行、
          走 probe 还是 execute、是否需要审批后恢复等关键信息。

        输出语义：
        - 未来会返回统一执行结果，用于写入账本并继续驱动主脑下一轮决策。
        """
        raise NotImplementedError("RuntimeExecutor.execute 尚未实现")
