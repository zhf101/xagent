"""
沙箱支持模块。
"""

from ..config import get_sandbox_image
from .base import (
    CodeType,
    ExecResult,
    Sandbox,
    SandboxConfig,
    SandboxInfo,
    SandboxNotFoundError,
    SandboxService,
    SandboxSnapshot,
    SandboxTemplate,
    TemplateType,
)
from .docker_sandbox import (
    DockerSandbox,
    DockerSandboxService,
    DockerStore,
    MemDockerStore,
    is_docker_available,
)

# 使用 `latest` 镜像作为降级策略
# 应通过环境变量 "SANDBOX_IMAGE" 在发布时固定版本（`latest` 可能导致缓存问题）
DEFAULT_SANDBOX_IMAGE = get_sandbox_image()

__all__ = [
    "DEFAULT_SANDBOX_IMAGE",
    "TemplateType",
    "CodeType",
    "SandboxTemplate",
    "SandboxConfig",
    "SandboxInfo",
    "SandboxNotFoundError",
    "SandboxSnapshot",
    "ExecResult",
    "Sandbox",
    "SandboxService",
    "DockerSandbox",
    "DockerStore",
    "MemDockerStore",
    "DockerSandboxService",
    "is_docker_available",
]

try:
    from .boxlite_sandbox import (
        BoxliteSandbox,
        BoxliteSandboxService,
        BoxliteStore,
        MemBoxliteStore,
    )

    __all__ += [
        "BoxliteSandbox",
        "BoxliteStore",
        "MemBoxliteStore",
        "BoxliteSandboxService",
    ]
except ImportError:
    pass
