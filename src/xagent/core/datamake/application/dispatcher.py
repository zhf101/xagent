"""
`Action Dispatch`（动作分发）模块。

这一层对应你设计图中的 `ACTION DISPATCH`（动作分发层）。
它接收的前提是：顶层主脑已经给出了明确的
`NextActionDecision`（下一动作决策）。

因此这里要解决的问题只有一个：
“这份已经确定好的决策，应该送到哪条通道执行？”

它不解决的问题是：
- 为什么要做这个动作
- 下一步是否应该换方向
- 当前业务目标是否已经达成
这些仍然属于顶层 `DataMakeReActPattern`（造数 ReAct 主控模式）。
"""

from __future__ import annotations

from typing import Any


class ActionDispatcher:
    """
    `ActionDispatcher`（动作分发器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`ACTION DISPATCH`（动作分发层）
    - 在你的设计里：控制层与各执行通道之间的路由关节

    主要职责：
    - 接收顶层 Agent 已经做出的结构化决策，而不是半成品意图。
    - 根据决策中的 `decision_mode` / `action_kind`，把请求路由给
      `InteractionBridge`（用户交互桥接器）、
      `SupervisionBridge`（人工监督桥接器）、
      `GuardService`（护栏服务）等下游组件。
    - 保持“纯分发、无业务决策权”的边界，避免 application 层反向长成第二个 Agent。
    """

    async def dispatch(self, decision: Any) -> Any:
        """
        分发一个已经确定好的 `NextActionDecision`（下一动作决策）。

        这里未来会做的事情包括：
- 识别当前决策属于 `interaction`（用户交互）、
  `supervision`（人工监督）还是 `execution`（执行）路径。
- 调用对应桥接器或护栏入口。
- 返回统一的 `ObservationEnvelope`（观察结果外壳）或等待态结果。

        这里明确不会做的事情：
- 重新推理“下一步到底该干什么”。
- 在分发层直接拼资源参数并下钻到底层资源适配器。
        """
        raise NotImplementedError("ActionDispatcher.dispatch 尚未实现")
