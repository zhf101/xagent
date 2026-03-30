"""
`HTTP Resource Adapter`（HTTP 资源适配器）模块。

它把已注册的 HTTP / API 资源动作映射到现有网络调用能力，
并在资源层统一约束请求方式、目标地址、鉴权与返回解析。
"""

from __future__ import annotations

from typing import Any


class HttpResourceAdapter:
    """
    `HttpResourceAdapter`（HTTP 资源适配器）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：HTTP / API 类资源的底层落地适配器

    主要职责：
    - 用资源语义包装现有 API Tool。
    - 让 Runtime 只执行已注册的受控 HTTP 动作。
    - 后续承接请求模板、鉴权注入、返回结构校验等能力。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个 HTTP 资源动作。

        这里不应该接受“任意 URL + 任意方法”的自由请求。
        """
        raise NotImplementedError("HttpResourceAdapter.execute 尚未实现")
