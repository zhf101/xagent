"""
OpenViking 身份头构造模块。

HTTP 模式下，xagent 通过请求头把当前 account / user / agent 身份映射给 OpenViking。
"""

from __future__ import annotations

from .config import OpenVikingSettings


def build_openviking_headers(
    settings: OpenVikingSettings,
    *,
    user_id: int | str,
    agent_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, str]:
    """
    构造 OpenViking HTTP 请求头。
    """

    headers = {
        "X-OpenViking-Account": str(account_id or settings.default_account),
        "X-OpenViking-User": str(user_id),
        "X-OpenViking-Agent": str(agent_id or settings.default_agent),
    }
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers
