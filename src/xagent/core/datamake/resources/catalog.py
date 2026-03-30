"""
`Resource Catalog`（资源目录）模块。

这个模块对应你设计里的资源动作总表。
它回答的问题是：
“系统当前到底有哪些受控资源能力可以被执行？”
"""

from __future__ import annotations

from typing import Any


class ResourceCatalog:
    """
    `ResourceCatalog`（资源目录）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：受控资源动作查询入口

    主要职责：
    - 统一暴露已注册的受控资源动作。
    - 提供资源能力、参数约束、风险标签、适配器信息等元数据查询。
    - 为 guard 和 runtime 提供一致的资源查找入口。
    """

    def get_action(self, resource_key: str, operation_key: str) -> Any:
        """
        按资源键和动作键查找受控动作。

        未来查到的不会只是一个函数句柄，而应是带完整元数据的资源动作描述。
        """
        raise NotImplementedError("ResourceCatalog.get_action 尚未实现")
