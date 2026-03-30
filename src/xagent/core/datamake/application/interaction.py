"""
`Interaction Channel`（用户交互通道）桥接模块。

这一层对应你设计里所有“需要用户补信息、澄清、确认”的分支。
它的核心作用是把内部决策语言，翻译成前端和用户能消费的交互语言，
然后再把用户回复翻译回系统内部统一的 `Observation`（观察结果）。
"""

from __future__ import annotations

from typing import Any


class InteractionBridge:
    """
    `InteractionBridge`（用户交互桥接器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`User / UI Channel`（用户 / 界面通道）
    - 在你的设计里：用户侧等待态与回流入口

    主要职责：
    - 创建用户澄清、补参、确认等等待态，形成可追踪的 `Interaction Ticket`
      （交互工单）。
    - 生成前端可以直接消费的展示结构，而不是把内部控制字段直接暴露给 UI。
    - 接收用户回复，并转为统一的 `InteractionObservation`
      （用户交互观察结果），供主脑进入下一轮决策。

    明确边界：
    - 不负责判断是否应该向用户提问；这个决定已经由顶层 Agent 做出。
    - 不负责审批裁决；人工审批属于 `SupervisionBridge`（人工监督桥接器）。
    - 不负责真正执行资源动作；执行路径会进入 guard / runtime。
    """

    async def open_ticket(self, decision: Any) -> Any:
        """
        创建 `Interaction Ticket`（交互工单）。

        输入是已经确定好的用户交互型决策；
        输出会是一个可持久化、可展示、可等待回复的交互请求对象。
        """
        raise NotImplementedError("InteractionBridge.open_ticket 尚未实现")

    async def consume_reply(self, reply: Any) -> Any:
        """
        消费用户回复，并转为统一 `InteractionObservation`（用户交互观察结果）。

        这个方法的意义是把前端输入重新拉回领域语言，
        让主脑后续处理时不需要关心 UI 表单细节。
        """
        raise NotImplementedError("InteractionBridge.consume_reply 尚未实现")


class UiResponseMapper:
    """
    `UiResponseMapper`（界面响应映射器）。

    所属分层：
    - 代码分层：`application`
    - 需求分层：`User / UI Channel`（用户 / 界面通道）
    - 在你的设计里：面向前端的展示协议适配器

    主要职责：
    - 把内部决策中的 `user_visible`（用户可见载荷）映射成具体前端消息、
      表单、确认卡片等结构。
    - 屏蔽底层控制字段，不让前端直接承接内部 runtime / ledger 语义。
    - 帮助前后端在“展示协议”层解耦。
    """

    def to_chat_payload(self, decision: Any) -> Any:
        """
        把内部决策映射为前端聊天载荷。

        未来这里会负责统一 chat payload、表单 schema、确认按钮等 UI 协议。
        """
        raise NotImplementedError("UiResponseMapper.to_chat_payload 尚未实现")
