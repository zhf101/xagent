"""OpenViking 请求身份映射。

OpenViking 的多租户模型天然支持 account / user / agent 三层隔离。
xagent 在 HTTP 模式下统一从这里构造 Header，避免业务层散落拼接逻辑。
"""

from __future__ import annotations

from typing import Dict, Optional

from .config import OpenVikingSettings


def build_openviking_headers(
    settings: OpenVikingSettings,
    *,
    user_id: int | str,
    agent_id: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, str]:
    """构造 OpenViking 请求头。"""

    headers = {
        "X-OpenViking-Account": account_id or settings.default_account,
        "X-OpenViking-User": str(user_id),
        "X-OpenViking-Agent": agent_id or settings.default_agent,
    }
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key
    return headers
