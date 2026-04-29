"""
沙箱(Sandbox)管理器 - 应用层沙箱实例管理

【合并来源】main分支多个提交:
- f6cdcd6 feat(sandbox): add docker-backed sandbox service (#274)
- 3fad64f refactor(sandbox): switch sandbox code sync to mount and refactor sandbox tool exec (#223)
- 208629a fix(sandbox): replace exec_run with get_archive for file existence check (#314)
- 4513470 feat(sandbox): boxlite support linux aarch64 (#277)

【沙箱是什么?】
沙箱是一个隔离的执行环境,用于:
- 安全执行不可信代码(Agent生成的Python脚本等)
- 防止恶意代码访问主机文件系统
- 限制CPU/内存使用,防止资源耗尽
- 提供标准化的工具执行环境

【为什么需要沙箱?】
在AI Agent场景中,Agent会生成并执行代码。如果不隔离:
- Agent可能生成rm -rf /等危险命令,破坏主机
- Agent可能访问敏感文件(如API密钥)
- Agent可能启动恶意进程

合并前的问题:
- 代码执行无隔离,直接在主机运行
- 无法限制资源使用
- 安全风险极高

合并后的改进:
- 支持2种实现: Docker容器、Boxlite轻量级沙箱
- 自动资源限制(CPU、内存)
- 文件系统隔离(只读挂载必要目录)
- 支持代码挂载卷机制,实现安全的代码同步

【架构设计】
┌──────────────────────────────────────────────┐
│         Agent Tool Execution                 │  ← Agent工具调用
├──────────────────────────────────────────────┤
│    Sandboxed Tool Wrapper                    │  ← 沙箱工具包装器
├──────────────────────────────────────────────┤
│    SandboxManager (本文件)                    │  ← 应用层管理器
├──────────────────────────────────────────────┤
│    SandboxService (sandbox/docker_sandbox.py)│ ← 服务层
├──────────────────────────────────────────────┤
│    Docker Engine / Boxlite                   │  ← 底层实现
└──────────────────────────────────────────────┘

【核心方法说明】
1. get_or_create() - 获取或创建沙箱实例(带锁保护,防止并发创建)
2. _cleanup_stale_sandboxes() - 清理过期沙箱(检测配置漂移)
3. _warmup_sandbox() - 预热沙箱(预加载镜像,加速首次启动)

【配置项说明】
- SANDBOX_ENABLED: 是否启用沙箱(默认false)
- SANDBOX_IMPLEMENTATION: 实现类型(docker/boxlite)
- SANDBOX_IMAGE: Docker镜像名
- SANDBOX_CPUS: CPU核心数限制
- SANDBOX_MEMORY: 内存限制(MB)
- SANDBOX_VOLUMES: 挂载卷配置(src:dst:mode)
- SANDBOX_ENV: 环境变量配置

【安全警告】
⚠️ 绝对不要将主机Docker socket(/var/run/docker.sock)挂载到沙箱!
   这等同于给沙箱root权限,攻击者可:
   - 启动特权容器
   - 挂载主机文件系统
   - 读取主机密钥
   - 完全逃逸沙箱

【合并后关键改动】
- 新增完整的沙箱管理体系(get_or_create/cleanup/warmup)
- 支持配置漂移检测(配置变更时自动重建沙箱)
- 改进代码同步机制(从exec_run改为mount,更高效安全)
- 支持Linux aarch64架构(Boxlite)
- 数据库持久化沙箱信息(SandboxInfo模型)
"""

import asyncio
import logging
import os
import threading
from typing import Optional

from ..config import (
    get_boxlite_home_dir,
    get_sandbox_cpus,
    get_sandbox_env,
    get_sandbox_image,
    get_sandbox_memory,
    get_sandbox_volumes,
    get_uploads_dir,
)
from ..core.tools.adapters.vibe.sandboxed_tool.sandboxed_tool_wrapper import (
    build_code_mount_volumes,
)
from ..sandbox import SandboxService
from ..sandbox.base import Sandbox, SandboxConfig, SandboxTemplate

logger = logging.getLogger(__name__)


class SandboxManager:
    """管理沙箱实例"""

    def __init__(self, service: SandboxService):
        """初始化沙箱管理器

        Args:
            service: 用于创建沙箱的 SandboxService 实例
        """
        self._service: SandboxService = service
        self._cache: dict[str, Sandbox] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @staticmethod
    def make_sandbox_name(lifecycle_type: str, lifecycle_id: str) -> str:
        """根据生命周期类型和 ID 构建沙箱名称"""
        return f"{lifecycle_type}::{lifecycle_id}"

    @staticmethod
    def parse_sandbox_name(name: str) -> tuple[str, str]:
        """解析沙箱名称为 (lifecycle_type, lifecycle_id)

        Raises:
            ValueError: 沙箱名称格式无效
        """
        parts = name.split("::", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid sandbox name format: {name!r}")
        return parts[0], parts[1]

    def _get_sandbox_image_and_config(self) -> tuple[str, SandboxConfig]:
        """从集中配置模块获取沙箱镜像和配置"""
        image = get_sandbox_image()
        config = SandboxConfig()

        # CPU 核心数
        cpus = get_sandbox_cpus()
        if cpus is not None:
            config.cpus = cpus

        # 内存
        memory = get_sandbox_memory()
        if memory is not None:
            config.memory = memory

        # 环境变量
        env = get_sandbox_env()
        if env:
            config.env = env

        # 挂载卷
        if volumes:
            config.volumes = volumes

        return image, config

    def _make_default_volumes(
        self,
        lifecycle_type: str,
        lifecycle_id: str,
        *,
        ensure_dir: bool,
    ) -> list[tuple[str, str, str]]:
        """构建默认卷挂载配置

        代码目录始终以只读方式挂载。
        用户工作区额外以读写方式挂载（仅适用于 user 生命周期类型）。

        Args:
            lifecycle_type: 例如 task|user
            lifecycle_id: 例如 task_id|user_id
            ensure_dir: True 时创建主机目录
        """
        # 代码挂载始终存在（至少 src/）
        volumes: list[tuple[str, str, str]] = list(build_code_mount_volumes() or [])

        # 以读写方式挂载用户工作区
        if lifecycle_type == "user":
            user_workspace = str((get_uploads_dir() / f"user_{lifecycle_id}").resolve())
            if ensure_dir:
                os.makedirs(user_workspace, exist_ok=True)
            volumes.append((user_workspace, user_workspace, "rw"))

        return volumes

    async def get_or_create_sandbox(
        self, lifecycle_type: str, lifecycle_id: str
    ) -> Sandbox:
        """获取或创建沙箱

        Args:
            lifecycle_type: 例如 task|user
            lifecycle_id: 例如 task_id|user_id

        Returns:
            沙箱实例
        """
        sandbox_name = self.make_sandbox_name(lifecycle_type, lifecycle_id)
        if sandbox_name in self._cache:
            return self._cache[sandbox_name]

        # 获取每个名称的锁,防止并发创建
        async with self._locks_guard:
            if sandbox_name not in self._locks:
                self._locks[sandbox_name] = asyncio.Lock()
            lock = self._locks[sandbox_name]

        async with lock:
            # 获取锁后再次检查
            if sandbox_name in self._cache:
                return self._cache[sandbox_name]

            # 从环境变量获取基础镜像和配置
            image, config = self._get_sandbox_image_and_config()
            logger.info(
                "Getting/creating sandbox: image=%r, cpus=%r, memory=%r, volumes=%r, env_count=%r",
                image,
                config.cpus,
                config.memory,
                config.volumes,
                len(config.env or {}),
            )

            template = SandboxTemplate(type="image", image=image)

            default_volumes = self._make_default_volumes(
                lifecycle_type, lifecycle_id, ensure_dir=True
            )
            config_volumes = list(config.volumes) if config.volumes else []
            # Merge volumes
            config.volumes = config_volumes + default_volumes

            logger.debug(f"Getting or creating sandbox for: {sandbox_name}")
            sandbox = await self._service.get_or_create(
                sandbox_name,
                template=template,
                config=config,
            )

            self._cache[sandbox_name] = sandbox
            return sandbox

    async def delete_sandbox(self, lifecycle_type: str, lifecycle_id: str) -> None:
        """删除沙箱

        Args:
            lifecycle_type: 例如 task|user
            lifecycle_id: 例如 task_id|user_id
        """
        sandbox_name = self.make_sandbox_name(lifecycle_type, lifecycle_id)
        try:
            await self._service.delete(sandbox_name)
            logger.debug(f"Sandbox deleted: {sandbox_name}")
        except Exception as e:
            logger.error(f"Failed to delete sandbox {sandbox_name}: {e}")
        finally:
            # 始终从缓存中清除 -- 即使失败,实例也可能处于未知状态,应重新创建
            self._cache.pop(sandbox_name, None)
            self._locks.pop(sandbox_name, None)

    async def warmup(self) -> None:
        """预热默认镜像
        预热时使用空配置,避免不必要的卷挂载。
        """
        image = get_sandbox_image()
        warmup_name = "__warmup__"
        try:
            template = SandboxTemplate(type="image", image=image)
            # 预热时使用空配置,不需要卷和环境变量
            warmup_config = SandboxConfig()
            async with await self._service.get_or_create(
                warmup_name, template=template, config=warmup_config
            ):
                pass
            await self._service.delete(warmup_name)
            logger.info(f"Sandbox image warmup completed: {image}")
        except Exception as e:
            logger.error(f"Failed to warmup sandbox image: {e}")

    async def cleanup(self) -> None:
        """停止所有运行中的沙箱

        删除配置（镜像、CPU、内存、卷）与当前环境不同的沙箱,
        以便下次使用时以正确的设置重新创建。

        Note:
            如果 ``get_uploads_dir()``（通过 ``XAGENT_UPLOADS_DIR`` 环境变量）在两次部署之间发生变化,
            所有用户沙箱将被检测为具有过时的卷挂载,将被删除以重新创建。
        """
        try:
            sandboxes = await self._service.list_sandboxes()
            if not sandboxes:
                logger.info("No sandboxes to clean up")
                return

            image, config = self._get_sandbox_image_and_config()

            for sb in sandboxes:
                try:
                    lifecycle_type, lifecycle_id = None, None
                    try:
                        lifecycle_type, lifecycle_id = self.parse_sandbox_name(sb.name)
                    except ValueError:
                        # 不是正常的托管沙箱名称,停止运行
                        if sb.state == "running":
                            box = await self._service.get_or_create(
                                sb.name, template=sb.template, config=sb.config
                            )
                            await box.stop()
                            logger.debug(f"Stopped sandbox: {sb.name}")
                        continue

                    # 如果配置已更改则删除沙箱(下次启动时强制重建)
                    image_changed = sb.template.image != image
                    cpus_changed = sb.config.cpus != config.cpus
                    memory_changed = sb.config.memory != config.memory

                    # 卷比较: None 和空列表视为相等,忽略顺序
                    old_volumes = sb.config.volumes or []

                    default_volumes = self._make_default_volumes(
                        lifecycle_type, lifecycle_id, ensure_dir=False
                    )
                    config_volumes = list(config.volumes) if config.volumes else []
                    # Merge volumes
                    new_volumes = config_volumes + default_volumes

                    volumes_changed = set(old_volumes) != set(new_volumes)

                    # 环境变量比较: None 和空字典视为相等
                    old_env = sb.config.env or {}
                    new_env = config.env or {}
                    env_changed = old_env != new_env

                    if (
                        image_changed
                        or cpus_changed
                        or memory_changed
                        or volumes_changed
                        or env_changed
                    ):
                        changes = []
                        if image_changed:
                            changes.append(f"image: {sb.template.image} -> {image}")
                        if cpus_changed:
                            changes.append(f"cpus: {sb.config.cpus} -> {config.cpus}")
                        if memory_changed:
                            changes.append(
                                f"memory: {sb.config.memory} -> {config.memory}"
                            )
                        if env_changed:
                            old_env_str = (
                                ";".join([f"{k}={v}" for k, v in old_env.items()])
                                if old_env
                                else "none"
                            )
                            new_env_str = (
                                ";".join([f"{k}={v}" for k, v in new_env.items()])
                                if new_env
                                else "none"
                            )
                            changes.append(f"env: {old_env_str} -> {new_env_str}")
                        if volumes_changed:
                            old_vol_str = (
                                ";".join([f"{h}:{g}:{m}" for h, g, m in old_volumes])
                                if old_volumes
                                else "none"
                            )
                            new_vol_str = (
                                ";".join([f"{h}:{g}:{m}" for h, g, m in new_volumes])
                                if new_volumes
                                else "none"
                            )
                            changes.append(f"volumes: {old_vol_str} -> {new_vol_str}")
                        logger.info(
                            f"Config changed for sandbox [{sb.name}]: "
                            f"{', '.join(changes)}, deleting"
                        )
                        await self._service.delete(sb.name)
                        continue

                    # 停止镜像匹配的运行中沙箱
                    if sb.state == "running":
                        box = await self._service.get_or_create(
                            sb.name, template=sb.template, config=sb.config
                        )
                        await box.stop()
                        logger.debug(f"Stopped sandbox: {sb.name}")
                except Exception as e:
                    logger.error(f"Failed to handle sandbox {sb.name}: {e}")

            self._cache.clear()
            self._locks.clear()
            logger.info("Sandbox cleanup completed")
        except Exception as e:
            logger.error(f"Failed to cleanup sandboxes: {e}")


# Global sandbox manager instance
_sandbox_manager: Optional[SandboxManager] = None
_sandbox_manager_lock = threading.Lock()
_sandbox_manager_initialized = False


def _create_sandbox_service() -> Optional[SandboxService]:
    """
    Create sandbox service based on environment configuration.

    Environment variables:
    - SANDBOX_ENABLED: Enable/disable sandbox (default: true)
    - SANDBOX_IMPLEMENTATION: Implementation type (default: docker)
      - docker: Use Docker sandbox
      - boxlite: Use Boxlite sandbox
    - BOXLITE_HOME_DIR: Boxlite home directory (optional)

    Returns:
        SandboxService instance or None if disabled
    """
    # Check if sandbox is enabled
    sandbox_enabled = os.getenv("SANDBOX_ENABLED", "false").lower() == "true"
    if not sandbox_enabled:
        logger.info("Sandbox is disabled via SANDBOX_ENABLED environment variable")
        return None

    # Get implementation type
    implementation = os.getenv("SANDBOX_IMPLEMENTATION", "docker")

    if implementation == "boxlite":
        return _create_boxlite_service()
    elif implementation == "docker":
        return _create_docker_service()
    else:
        logger.warning(
            f"Unknown sandbox implementation: {implementation}, falling back to docker"
        )
        return _create_docker_service()


def _create_boxlite_service() -> Optional[SandboxService]:
    """Create Boxlite sandbox service."""
    try:
        from ..sandbox import BoxliteSandboxService
    except ImportError:
        logger.error("boxlite is not installed.")
        return None

    from .sandbox_store import DBBoxliteStore

    store = DBBoxliteStore()
    # Get home directory
    home_dir = get_boxlite_home_dir()

    service = None
    try:
        service = BoxliteSandboxService(
            store=store, home_dir=None if home_dir is None else str(home_dir)
        )
        logger.info(
            f"Created Boxlite sandbox service (home_dir={home_dir or 'default'})"
        )
    except Exception as e:
        logger.error(f"Failed to create Boxlite sandbox service: {e}")

    return service


def _create_docker_service() -> Optional[SandboxService]:
    """Create Docker sandbox service."""
    try:
        from ..sandbox import DockerSandboxService
    except ImportError:
        logger.error("docker sandbox dependencies are not installed.")
        return None

    from .sandbox_store import DBDockerStore

    store = DBDockerStore()

    service = None
    try:
        service = DockerSandboxService(store=store)
        logger.info("Created Docker sandbox service")
    except Exception as e:
        logger.error(f"Failed to create Docker sandbox service: {e}")

    return service


def get_sandbox_manager() -> Optional[SandboxManager]:
    """
    Get or create global sandbox manager instance.

    Thread-safe singleton pattern with double-checked locking.

    Returns:
        SandboxManager instance or None if sandbox is disabled
    """
    global _sandbox_manager, _sandbox_manager_initialized

    # Fast path: already initialized (either successfully or service was None)
    if _sandbox_manager_initialized:
        return _sandbox_manager

    # Slow path: need to initialize
    with _sandbox_manager_lock:
        # Double-check after acquiring lock
        if _sandbox_manager_initialized:
            return _sandbox_manager

        # Get sandbox service
        service = _create_sandbox_service()
        if service is None:
            _sandbox_manager_initialized = True
            return None

        # Create sandbox manager
        _sandbox_manager = SandboxManager(service)
        _sandbox_manager_initialized = True
        logger.info("Created global sandbox manager")

        return _sandbox_manager
