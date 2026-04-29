"""
Sandbox management in application layer.
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
    """
    Manages sandbox instances.
    """

    def __init__(self, service: SandboxService):
        """
        Initialize sandbox manager.

        Args:
            service: SandboxService instance for creating sandboxes
        """
        self._service: SandboxService = service
        self._cache: dict[str, Sandbox] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    @staticmethod
    def make_sandbox_name(lifecycle_type: str, lifecycle_id: str) -> str:
        """Build a sandbox name from lifecycle type and id."""
        return f"{lifecycle_type}::{lifecycle_id}"

    @staticmethod
    def parse_sandbox_name(name: str) -> tuple[str, str]:
        """Parse a sandbox name into (lifecycle_type, lifecycle_id).

        Raises:
            ValueError: Invalid sandbox name format.
        """
        parts = name.split("::", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid sandbox name format: {name!r}")
        return parts[0], parts[1]

    def _get_sandbox_image_and_config(self) -> tuple[str, SandboxConfig]:
        """Get sandbox image and configuration from centralized config module."""
        image = get_sandbox_image()
        config = SandboxConfig()

        # CPU
        cpus = get_sandbox_cpus()
        if cpus is not None:
            config.cpus = cpus

        # MEM
        memory = get_sandbox_memory()
        if memory is not None:
            config.memory = memory

        # ENV
        env = get_sandbox_env()
        if env:
            config.env = env

        # VOL
        volumes = get_sandbox_volumes()
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
        """
        Build default volume mounts.

        Code directories are always mounted read-only.
        User workspace is additionally mounted read-write for user lifecycle type.

        Args:
            lifecycle_type: e.g. task|user
            lifecycle_id: e.g. task_id|user_id
            ensure_dir: When True, create the host directory
        """
        # Code mounts are always present (at least src/)
        volumes: list[tuple[str, str, str]] = list(build_code_mount_volumes())

        # Mount user workspace as read-write
        if lifecycle_type == "user":
            user_workspace = str((get_uploads_dir() / f"user_{lifecycle_id}").resolve())
            if ensure_dir:
                os.makedirs(user_workspace, exist_ok=True)
            volumes.append((user_workspace, user_workspace, "rw"))

        return volumes

    async def get_or_create_sandbox(
        self, lifecycle_type: str, lifecycle_id: str
    ) -> Sandbox:
        """
        Get or create a sandbox.

        Args:
            lifecycle_type: e.g. task|user
            lifecycle_id: e.g. task_id|user_id

        Returns:
            Sandbox instance
        """
        sandbox_name = self.make_sandbox_name(lifecycle_type, lifecycle_id)
        if sandbox_name in self._cache:
            return self._cache[sandbox_name]

        # Acquire per-name lock to prevent concurrent creation
        async with self._locks_guard:
            if sandbox_name not in self._locks:
                self._locks[sandbox_name] = asyncio.Lock()
            lock = self._locks[sandbox_name]

        async with lock:
            # Double-check after acquiring lock
            if sandbox_name in self._cache:
                return self._cache[sandbox_name]

            # Get base image and config from environment variables
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
        """
        Delete sandbox.

        Args:
            lifecycle_type: e.g. task|user
            lifecycle_id: e.g. task_id|user_id
        """
        sandbox_name = self.make_sandbox_name(lifecycle_type, lifecycle_id)
        try:
            await self._service.delete(sandbox_name)
            logger.debug(f"Sandbox deleted: {sandbox_name}")
        except Exception as e:
            logger.error(f"Failed to delete sandbox {sandbox_name}: {e}")
        finally:
            # Always evict from cache — even on failure the instance
            # may be in an unknown state and should be recreated.
            self._cache.pop(sandbox_name, None)
            self._locks.pop(sandbox_name, None)

    async def warmup(self) -> None:
        """
        Warmup default image.
        Uses empty config for warmup to avoid unnecessary volume mounts.
        """
        image = get_sandbox_image()
        warmup_name = "__warmup__"
        try:
            template = SandboxTemplate(type="image", image=image)
            # Use empty config for warmup - no need for volumes/env
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
        """Stop all running sandboxes.

        Delete sandboxes whose config (image, cpus, memory, volumes)
        differs from the current environment so they get recreated
        with the correct settings next time.

        Note:
            If ``get_uploads_dir()`` (via ``XAGENT_UPLOADS_DIR`` env var) changes
            between deployments, all user sandboxes will be detected as
            having stale volume mounts and will be deleted for recreation.
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
                        # Not a normal managed sandbox name, stop
                        if sb.state == "running":
                            box = await self._service.get_or_create(
                                sb.name, template=sb.template, config=sb.config
                            )
                            await box.stop()
                            logger.debug(f"Stopped sandbox: {sb.name}")
                        continue

                    # Delete sandbox if config changed (force recreate on next start)
                    image_changed = sb.template.image != image
                    cpus_changed = sb.config.cpus != config.cpus
                    memory_changed = sb.config.memory != config.memory

                    # volumes comparison: None and empty list are treated as equal, ignore order
                    old_volumes = sb.config.volumes or []

                    default_volumes = self._make_default_volumes(
                        lifecycle_type, lifecycle_id, ensure_dir=False
                    )
                    config_volumes = list(config.volumes) if config.volumes else []
                    # Merge volumes
                    new_volumes = config_volumes + default_volumes

                    volumes_changed = set(old_volumes) != set(new_volumes)

                    # env comparison: None and empty dict are treated as equal
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

                    # Stop running sandboxes with matching image
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
