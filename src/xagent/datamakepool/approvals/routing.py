"""审批候选人路由辅助。

这不是最终的审批流引擎，而是一个轻量、纯函数式的路由辅助模块，
用于把“角色要求 + 系统范围”映射成一个可用审批人。

当前用途：
- 为单元测试提供稳定的审批路由约束
- 给后续审批单分发 / 默认候选人选择保留纯逻辑入口
"""

from __future__ import annotations


def route_approver(
    *,
    required_role: str,
    system_short: str | None,
    bindings: dict[str, list[str]],
) -> str | None:
    """从简单绑定映射里路由一个审批人。

    约定：
    - `bindings` 的 key 是用户名
    - value 里的普通 `system_short` 表示该用户是对应系统的普通管理员
    - 特殊值 `*` 表示全局系统管理员，可审批所有系统

    这是为了保持测试与纯逻辑工具简单，不在这里引入 ORM 依赖。
    """

    normalized_system = str(system_short or "").strip().lower()
    global_candidate: str | None = None

    for username in sorted(bindings.keys()):
        scopes = {str(scope).strip().lower() for scope in bindings[username]}
        if "*" in scopes:
            global_candidate = global_candidate or username
        if required_role == "normal_admin" and normalized_system and normalized_system in scopes:
            return username

    return global_candidate
