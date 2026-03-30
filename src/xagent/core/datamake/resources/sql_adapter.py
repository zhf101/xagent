"""
`SQL Resource Adapter`（SQL 资源适配器）模块。

它不是为了支持任意 SQL 文本自由执行，
而是为了把“受控 SQL 资源动作”映射到 xagent 现有 SQL 能力。
"""

from __future__ import annotations

from typing import Any


class SqlResourceAdapter:
    """
    `SqlResourceAdapter`（SQL 资源适配器）。

    所属分层：
    - 代码分层：`resources`
    - 需求分层：`Resource Plane`（资源平面）
    - 在你的设计里：SQL 类资源的底层落地适配器

    主要职责：
    - 用资源语义包装现有 SQL Tool。
    - 让 Runtime 面对的是受控 SQL 动作，而不是任意 SQL 文本。
    - 在未来承接参数绑定、只读限制、结果映射等安全控制。
    """

    async def execute(self, contract: Any) -> Any:
        """
        执行一个 SQL 资源动作。

        输入会是标准运行时契约，而不是自由拼接 SQL 的原始请求。
        """
        raise NotImplementedError("SqlResourceAdapter.execute 尚未实现")
