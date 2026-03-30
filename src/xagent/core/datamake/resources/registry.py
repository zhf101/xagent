"""
`Resource Registry`（资源注册中心）模块。

它负责接纳各类资源动作定义，并把它们沉淀成系统可查询、可治理的注册表。
"""

from __future__ import annotations

from typing import Any


class ResourceRegistry:
    """
    `ResourceRegistry`（资源注册中心）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：资源能力登记入口

    主要职责：
    - 注册受控资源动作及其元信息。
    - 为 `ResourceCatalog`（资源目录）提供底层查找能力。
    - 把分散的资源能力收敛成统一注册表。
    """

    def register(self, resource: Any) -> None:
        """
        注册一个资源或资源动作。

        未来注册内容通常会包含资源标识、动作标识、参数 schema、适配器类型等。
        """
        raise NotImplementedError("ResourceRegistry.register 尚未实现")
