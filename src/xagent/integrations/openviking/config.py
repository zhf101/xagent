"""OpenViking 集成配置。

这里统一读取环境变量，避免业务代码各处直接访问 `os.getenv`，
后续如果要迁移到数据库或系统设置，也只需要调整这一层。
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from pydantic import BaseModel, Field


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class OpenVikingSettings(BaseModel):
    """OpenViking 运行配置。

    第一阶段只支持 HTTP 模式，目的是把 OpenViking 作为独立上下文服务接入，
    避免把 xagent 主进程和 OpenViking 的运行时强耦合。
    """

    enabled: bool = False
    mode: str = "http"
    base_url: str = "http://127.0.0.1:1933"
    auth_mode: str = "trusted"
    api_key: Optional[str] = None
    default_account: str = "xagent"
    default_agent: str = "default"
    search_enabled: bool = True
    memory_enabled: bool = True
    skill_index_enabled: bool = False
    resource_sync_enabled: bool = False
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)

    @property
    def http_enabled(self) -> bool:
        return self.enabled and self.mode.lower() == "http"


@lru_cache(maxsize=1)
def get_openviking_settings() -> OpenVikingSettings:
    """读取 OpenViking 配置并缓存。"""

    return OpenVikingSettings(
        enabled=_parse_bool(os.getenv("XAGENT_OPENVIKING_ENABLED"), False),
        mode=os.getenv("XAGENT_OPENVIKING_MODE", "http"),
        base_url=os.getenv("XAGENT_OPENVIKING_BASE_URL", "http://127.0.0.1:1933"),
        auth_mode=os.getenv("XAGENT_OPENVIKING_AUTH_MODE", "trusted"),
        api_key=os.getenv("XAGENT_OPENVIKING_API_KEY"),
        default_account=os.getenv("XAGENT_OPENVIKING_DEFAULT_ACCOUNT", "xagent"),
        default_agent=os.getenv("XAGENT_OPENVIKING_DEFAULT_AGENT", "default"),
        search_enabled=_parse_bool(
            os.getenv("XAGENT_OPENVIKING_SEARCH_ENABLED"), True
        ),
        memory_enabled=_parse_bool(
            os.getenv("XAGENT_OPENVIKING_MEMORY_ENABLED"), True
        ),
        skill_index_enabled=_parse_bool(
            os.getenv("XAGENT_OPENVIKING_SKILL_INDEX_ENABLED"), False
        ),
        resource_sync_enabled=_parse_bool(
            os.getenv("XAGENT_OPENVIKING_RESOURCE_SYNC_ENABLED"), False
        ),
        timeout_seconds=float(
            os.getenv("XAGENT_OPENVIKING_TIMEOUT_SECONDS", "15.0")
        ),
    )
