"""
`Dubbo Resource Adapter`（Dubbo 资源适配器）模块。

当前仓库中没有现成 Dubbo 适配器，
这个文件先作为“资源层如何扩展新协议”的骨架示例占位。
"""

from __future__ import annotations

from typing import Any


class DubboResourceAdapter:
    """
    `DubboResourceAdapter`（Dubbo 资源适配器）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：Dubbo 类资源的底层落地适配器

    主要职责：
    - 对接 Dubbo 服务调用。
    - 把 Dubbo 方法暴露为受控资源动作。
    - 作为资源层扩展新协议的一种参考形态。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个 Dubbo 资源动作。

        后续若真接入 Dubbo，这里还需要补服务发现、序列化、超时控制等细节。
        """
        raise NotImplementedError("DubboResourceAdapter.execute 尚未实现")
