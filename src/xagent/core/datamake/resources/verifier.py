"""
`Resource Verifier`（资源验证器）模块。

它和 Probe 的关系是：
- Probe 更像一次运行时探测执行
- Verifier 更像资源侧的基础可用性验证能力
"""

from __future__ import annotations

from typing import Any


class ResourceVerifier:
    """
    `ResourceVerifier`（资源验证器）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：资源侧基础校验器

    主要职责：
    - 做资源级探测和验证。
    - 为 `GuardService`（护栏服务）或 `ProbeExecutor`（探测执行器）
      提供基础验证能力。
    - 把“资源本身是否可用”的校验从业务流程里抽离出来。
    """

    async def verify(self, resource_action: Any) -> Any:
        """
        验证一个资源动作是否可执行。

        未来返回结果应包含可用性、失败原因、建议下一步等结构化信息。
        """
        raise NotImplementedError("ResourceVerifier.verify 尚未实现")
