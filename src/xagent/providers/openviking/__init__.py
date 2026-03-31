"""
OpenViking provider module.

当前只提供 Phase 1 所需的最小 HTTP 集成门面，
供 datamake / SQL Brain 在需要时把 OpenViking 当作外部上下文服务使用。
"""

from .config import OpenVikingSettings, get_openviking_settings
from .service import OpenVikingService, get_openviking_service
from .sync import (
    build_kb_resource_target_uri,
    sync_kb_resource_to_openviking,
    sync_skills_to_openviking,
)

__all__ = [
    "OpenVikingSettings",
    "OpenVikingService",
    "build_kb_resource_target_uri",
    "get_openviking_service",
    "get_openviking_settings",
    "sync_kb_resource_to_openviking",
    "sync_skills_to_openviking",
]
