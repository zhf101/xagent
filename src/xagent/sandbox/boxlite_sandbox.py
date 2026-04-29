"""
Boxlite 沙箱实现。
"""

from __future__ import annotations

import abc
import asyncio
import logging
import os
import shlex
import tempfile
import textwrap
import uuid
from typing import Optional

import boxlite  # type: ignore[import-not-found]
from boxlite import SimpleBox  # type: ignore[unused-ignore]

from ..config import get_sandbox_image
from .base import (
    CodeType,
    ExecResult,
    Sandbox,
    SandboxConfig,
    SandboxInfo,
    SandboxService,
    SandboxSnapshot,
    SandboxTemplate,
)

logger = logging.getLogger(__name__)

DEFAULT_SANDBOX_IMAGE = get_sandbox_image()


class BoxliteStore(abc.ABC):
    """
    持久化 Boxlite 数据的存储层。
    """

    @abc.abstractmethod
    def get_info(self, name: str) -> Optional[SandboxInfo]:
        """获取沙箱信息。"""

    @abc.abstractmethod
    def add_info(self, name: str, info: SandboxInfo) -> None:
        """添加沙箱信息。"""

    @abc.abstractmethod
    def update_info_state(self, name: str, state: str) -> None:
        """更新沙箱信息状态。"""

    @abc.abstractmethod
    def delete_info(self, name: str) -> None:
        """删除沙箱信息。"""


class MemBoxliteStore(BoxliteStore):
    """
    BoxliteStore 的内存实现。
    """

    def __init__(self) -> None:
        self._metadata: dict[str, SandboxInfo] = {}

    def get_info(self, name: str) -> Optional[SandboxInfo]:
        return self._metadata.get(name)

    def add_info(self, name: str, info: SandboxInfo) -> None:
        self._metadata[name] = info

    def update_info_state(self, name: str, state: str) -> None:
        if name in self._metadata:
            self._metadata[name].state = state

    def delete_info(self, name: str) -> None:
        if name in self._metadata:
            del self._metadata[name]


def _get_state(raw_info: boxlite.BoxInfo) -> str:  # type: ignore[no-any-unimported]
    """将 boxlite BoxInfo.state 映射为 'running' / 'stopped' / 'unknown'。"""
    state = raw_info.state.status.lower()
    if "running" in state:
        return "running"
    if any(key in state for key in ("stopped", "paused", "exited", "created")):
        return "stopped"
    return "unknown"


def _get_info_from_box_info(raw_info: boxlite.BoxInfo) -> SandboxInfo:  # type: ignore[no-any-unimported]
    tpl = SandboxTemplate(
        type="image",
        image=raw_info.image,
    )
    cfg = SandboxConfig(
        cpus=raw_info.cpus,
        memory=raw_info.memory_mib,
        env=None,  # 无法获取
        volumes=None,  # 无法获取
        network_isolated=None,  # 无法获取
        ports=None,  # 无法获取
    )
    info = SandboxInfo(
        name=raw_info.name,
        state=_get_state(raw_info),
        template=tpl,
        config=cfg,
        created_at=raw_info.created_at,
    )
    return info


class BoxliteSandbox(Sandbox):
    """
    Boxlite 实现。
    """

    def __init__(  # type: ignore[no-any-unimported]
        self,
        sandbox_name: str,
        box: SimpleBox,
        info: SandboxInfo,
        store: BoxliteStore,
    ) -> None:
        self._box = box
        self._name = sandbox_name
        self._info = info
        self._store = store

    # --- 属性 ---

    @property
    def name(self) -> str:
        """沙箱名称（唯一标识符）。"""
        return self._name

    # --- 生命周期 ---

    async def stop(self) -> None:
        """停止沙箱，保留其状态。"""
        await self._box.stop()
        self._store.update_info_state(self._name, "stopped")

    async def info(self) -> SandboxInfo:
        """获取沙箱状态信息。"""
        # 实时更新状态
        # box.info() 在 box 已停止后会报错，因此需要用 box._runtime.get_info(name) 方法替代。
        box_info = await self._box._runtime.get_info(self._name)
        self._info.state = _get_state(box_info)

        return self._info

    # --- 执行 ---

    async def exec(
        self,
        command: str,
        *args: str,
        env: Optional[dict[str, str]] = None,
    ) -> ExecResult:
        res = await self._box.exec(command, *args, env=env)

        # 过滤掉 seccomp 告警（macOS 上的已知问题，通常出现在第一行）
        stderr = res.stderr
        if stderr and "seccomp not available" in stderr:
            lines = stderr.split("\n", 1)  # 仅分割第一行
            if len(lines) > 0 and "seccomp not available" in lines[0]:
                # 移除第一行，保留其余内容
                stderr = lines[1] if len(lines) > 1 else ""

        return ExecResult(
            exit_code=res.exit_code,
            stdout=res.stdout,
            stderr=stderr,
            error_message=res.error_message,
        )

    async def run_code(
        self,
        code: str,
        code_type: CodeType = "python",
        env: Optional[dict[str, str]] = None,
    ) -> ExecResult:
        """
        执行代码片段。
        """
        code = textwrap.dedent(code)
        if code_type == "python":
            return await self.exec("python", "-c", code, env=env)
        elif code_type == "javascript":
            return await self.exec("node", "-e", code, env=env)
        raise ValueError(f"Unsupported code type: {code_type}")

    # --- 文件操作 ---

    async def upload_file(
        self, local_path: str, remote_path: str, overwrite: bool = False
    ) -> None:
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"Local file not found: {local_path}")

        if not overwrite:
            check = await self.exec("test", "-e", remote_path)
            if check.exit_code == 0:
                raise FileExistsError(f"Remote file already exists: {remote_path}")

        # 先复制到临时目录（如果直接复制到挂载目录，宿主机上不可读）
        # 注意：不能使用 /tmp，因为它是 tmpfs 挂载，copy_in 会失败
        # 使用 /var/tmp 或其他非 tmpfs 目录

        temp_filename = f"_upload_{uuid.uuid4().hex}"
        temp_remote = f"/var/tmp/{temp_filename}"

        # 确保 /var/tmp 存在
        await self.exec("mkdir", "-p", "/var/tmp")

        # copy_in 到临时位置
        await self._box.copy_in(local_path, temp_remote, overwrite=overwrite)

        # 验证临时文件已存在
        check = await self.exec("test", "-f", temp_remote)
        if check.exit_code != 0:
            raise RuntimeError(
                f"Failed to copy file to temporary location: {temp_remote}"
            )

        # 创建目标目录
        remote_dir = os.path.dirname(remote_path)
        if remote_dir:
            await self.exec("mkdir", "-p", remote_dir)

        temp_remote_quoted = shlex.quote(temp_remote)
        remote_path_quoted = shlex.quote(remote_path)

        if overwrite:
            result = await self.exec(
                "sh",
                "-c",
                f"mv {temp_remote_quoted} {remote_path_quoted}",
            )
        else:
            result = await self.exec(
                "sh",
                "-c",
                f"if [ -e {remote_path_quoted} ]; then exit 100; fi; mv {temp_remote_quoted} {remote_path_quoted}",
            )
            if result.exit_code == 100:
                await self.exec("rm", "-f", temp_remote)
                raise FileExistsError(f"Remote file already exists: {remote_path}")

        if result.exit_code != 0:
            # 清理临时文件
            await self.exec("rm", "-f", temp_remote)
            raise RuntimeError(f"Failed to move file to {remote_path}: {result.stderr}")

    async def download_file(
        self, remote_path: str, local_path: str, overwrite: bool = False
    ) -> None:
        check = await self.exec("test", "-e", remote_path)
        if check.exit_code != 0:
            raise FileNotFoundError(f"Remote file not found: {remote_path}")

        if not overwrite and os.path.exists(local_path):
            raise FileExistsError(f"Local file already exists: {local_path}")

        # 先复制到临时目录（避免卷挂载问题）

        temp_filename = f"_download_{uuid.uuid4().hex}"
        temp_remote = f"/var/tmp/{temp_filename}"

        # 确保 /var/tmp 存在
        await self.exec("mkdir", "-p", "/var/tmp")

        # 使用 cp 命令复制到临时位置（支持卷挂载）
        result = await self.exec("cp", remote_path, temp_remote)
        if result.exit_code != 0:
            raise RuntimeError(
                f"Failed to copy file to temporary location: {result.stderr}"
            )

        # 创建本地目录
        local_dir = os.path.dirname(local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)

        # 从临时位置 copy_out 到本地
        try:
            await self._box.copy_out(temp_remote, local_path, overwrite=overwrite)
        finally:
            # 清理临时文件
            await self.exec("rm", "-f", temp_remote)

    async def write_file(
        self, content: str, remote_path: str, overwrite: bool = False
    ) -> None:
        # 写入本地临时文件
        fd, tmp = tempfile.mkstemp(suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)

            # 使用 upload_file 上传（支持卷挂载）
            await self.upload_file(tmp, remote_path, overwrite=overwrite)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    async def read_file(self, remote_path: str) -> str:
        # 使用 download_file 读取（支持卷挂载）
        fd, tmp = tempfile.mkstemp(suffix=".tmp")
        os.close(fd)
        try:
            await self.download_file(remote_path, tmp, overwrite=True)
            with open(tmp, "r", encoding="utf-8") as f:
                return f.read()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


async def _create_or_reuse_box(  # type: ignore[no-any-unimported]
    name: str,
    template: SandboxTemplate,
    config: SandboxConfig,
    runtime: boxlite.Boxlite,
) -> SimpleBox:
    """创建一个新的 Box。"""
    # 构建 SimpleBox 参数
    kwargs: dict = {
        "image": template.image,
        "cpus": config.cpus,
        "memory_mib": config.memory,
        "disk_size_gb": 10,  # 增大以容纳软件包和工作区文件
        "auto_remove": False,  # 不自动删除，保留状态
        "runtime": runtime,
        "name": name,
        "reuse_existing": True,  # 允许复用已有 box
        "working_dir": config.working_dir,
    }

    if config.env:
        kwargs["env"] = list(config.env.items())

    if config.volumes:
        kwargs["volumes"] = [
            (h, g, mode.lower() == "ro") for h, g, mode in config.volumes
        ]

    if config.ports:
        kwargs["ports"] = config.ports

    if config.network_isolated:
        sec = boxlite.SecurityOptions()
        sec.network_enabled = False
        kwargs["advanced"] = sec

    # 创建 SimpleBox
    box = SimpleBox(**kwargs)
    await box.start()
    return box


class BoxliteSandboxService(SandboxService):
    """
    Boxlite 实现。
    """

    def __init__(self, store: BoxliteStore, home_dir: Optional[str] = None) -> None:
        """
        初始化 BoxliteSandboxService。

        Args:
            store: 用于持久化沙箱信息的存储层
            home_dir: Boxlite 的主目录，用于存储镜像和虚拟机等数据。
                    若为 None，则使用默认目录（通常为 ~/.boxlite）
        """
        if home_dir:
            self._runtime = boxlite.Boxlite(boxlite.Options(home_dir=home_dir))
        else:
            self._runtime = boxlite.Boxlite.default()
        self._store = store
        # 用于保护并发创建的锁，每个名称一把锁
        self._locks: dict[str, asyncio.Lock] = {}
        # 用于保护 _locks 字典本身的锁
        self._locks_lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        template: Optional[SandboxTemplate] = None,
        config: Optional[SandboxConfig] = None,
    ) -> BoxliteSandbox:
        # 不支持快照创建
        if template is not None and template.type == "snapshot":
            raise NotImplementedError("Unsupported")

        # 获取或创建此名称的锁
        async with self._locks_lock:
            if name not in self._locks:
                self._locks[name] = asyncio.Lock()
            lock = self._locks[name]

        # 使用锁保护整个 get_or_create 流程
        async with lock:
            # 检查 box 是否已存在
            raw_box = await self._runtime.get(name)
            if raw_box:
                # Box 已存在，获取或恢复信息
                info = self._store.get_info(name)
                if not info:
                    # 数据库数据丢失，从 boxlite 重新读取
                    info = _get_info_from_box_info(raw_box.info())
            else:
                # Box 不存在，创建新的
                tpl = template or SandboxTemplate(
                    type="image", image=DEFAULT_SANDBOX_IMAGE
                )
                cfg = config or SandboxConfig()
                info = SandboxInfo(name=name, state="running", template=tpl, config=cfg)

            # 创建或复用 box
            box = await _create_or_reuse_box(
                name, info.template, info.config, self._runtime
            )

            # 如果是新建的 box，更新 created_at
            if box.created:
                info.created_at = box.info().created_at
                self._store.add_info(name, info)

            # 更新状态
            self._store.update_info_state(name, "running")
            return BoxliteSandbox(
                sandbox_name=name, box=box, info=info, store=self._store
            )

    async def list_sandboxes(self) -> list[SandboxInfo]:
        # 以 boxlite 为准
        raw_list: list[boxlite.BoxInfo] = await self._runtime.list_info()  # type: ignore[no-any-unimported]
        result: list[SandboxInfo] = []
        for raw_info in raw_list:
            box_name = raw_info.name
            info = self._store.get_info(box_name)
            if info:
                result.append(info)
                info.state = _get_state(raw_info)  # 刷新状态
            else:
                # 数据库数据丢失，从 boxlite 重新读取
                info = _get_info_from_box_info(raw_info)
                result.append(info)
        return result

    async def delete(self, name: str) -> None:
        box = await self._runtime.get(name)
        if not box:
            self._store.delete_info(name)
            # 清除锁
            async with self._locks_lock:
                self._locks.pop(name, None)
            return

        try:
            await self._runtime.remove(name, force=True)
            self._store.delete_info(name)
            # 清除锁
            async with self._locks_lock:
                self._locks.pop(name, None)
        except Exception as e:
            raise RuntimeError(f"delete {name!r} error: {e}") from e

    async def supports_snapshots(self) -> bool:
        return False

    async def create_snapshot(self, name: str, snapshot_id: str) -> SandboxSnapshot:
        raise NotImplementedError("Unsupported")

    async def list_snapshots(self) -> list[SandboxSnapshot]:
        raise NotImplementedError("Unsupported")

    async def delete_snapshot(self, snapshot_id: str) -> None:
        raise NotImplementedError("Unsupported")
