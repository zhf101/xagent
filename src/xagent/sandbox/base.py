"""
沙箱服务抽象接口。
"""

from __future__ import annotations

import abc
from typing import Literal, Optional

from pydantic import BaseModel, Field

TemplateType = Literal["image", "snapshot"]
"""支持的模板类型。"""

CodeType = Literal["python", "javascript"]
"""支持的代码执行类型。"""


class SandboxNotFoundError(Exception):
    """当请求的沙箱资源不存在时抛出。"""


class SandboxTemplate(BaseModel):
    """
    创建沙箱的模板。

    `type="image"` 从容器镜像创建沙箱。

    `type="snapshot"` 从之前提交的文件系统快照创建沙箱。
    快照仅为新沙箱初始文件系统内容提供创建模板；
    运行时配置（如工作目录、环境变量、卷挂载、网络隔离、
    端口映射）仍来自当前 `get_or_create()` 调用中的 `SandboxConfig`。
    """

    type: Optional[TemplateType] = Field(default="image", description="模板类型")

    image: Optional[str] = Field(
        default=None, description="容器镜像，type=image 时必填"
    )

    snapshot_id: Optional[str] = Field(
        default=None, description="快照 ID，type=snapshot 时必填"
    )


class SandboxConfig(BaseModel):
    """
    创建沙箱的配置参数。
    """

    working_dir: Optional[str] = Field(default="/home", description="工作目录")

    cpus: Optional[int] = Field(default=1, ge=1, description="CPU 核心数上限")

    memory: Optional[int] = Field(default=512, ge=128, description="内存上限（MB）")

    env: Optional[dict[str, str]] = Field(
        default=None, description="要注入的环境变量"
    )

    volumes: Optional[list[tuple[str, str, str]]] = Field(
        default=None,
        description="卷挂载，格式为 (host_path, guest_path, mode)。mode: 'ro'（只读）或 'rw'（读写）",
    )

    network_isolated: Optional[bool] = Field(
        default=False,
        description="网络隔离。True 表示阻断外部网络访问",
    )

    ports: Optional[list[tuple[int, int]]] = Field(
        default=None, description="端口映射，格式为 [(host_port, guest_port)]"
    )


class SandboxInfo(BaseModel):
    """沙箱状态信息。"""

    name: str = Field(description="沙箱名称")

    state: str = Field(description="沙箱状态：'running'、'stopped' 或 'unknown'")

    template: SandboxTemplate = Field(
        description="用于创建此沙箱的模板"
    )

    config: SandboxConfig = Field(
        description="用于创建此沙箱的配置"
    )

    created_at: Optional[str] = Field(
        default=None, description="创建时间（ISO 8601 格式）"
    )


class SandboxSnapshot(BaseModel):
    """沙箱快照信息。"""

    snapshot_id: str = Field(description="快照 ID")

    metadata: dict = Field(default_factory=dict, description="快照元数据")

    created_at: Optional[str] = Field(
        default=None, description="创建时间（ISO 8601 格式）"
    )


class ExecResult(BaseModel):
    """命令或代码的执行结果。"""

    exit_code: int = Field(
        description="退出码。0 表示成功，非零表示失败"
    )

    stdout: str = Field(description="标准输出")

    stderr: str = Field(description="标准错误输出")

    error_message: Optional[str] = Field(default=None, description="错误信息")

    @property
    def success(self) -> bool:
        return self.exit_code == 0


class Sandbox(abc.ABC):
    """
    沙箱实例抽象接口。

    支持两种使用模式：

        # 手动停止
        try:
            result = await sandbox.exec("echo hello")
        finally:
            await sandbox.stop()

        # 使用异步上下文管理器自动停止
        async with sandbox:
            result = await sandbox.exec("echo hello")
    """

    async def __aenter__(self) -> "Sandbox":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.stop()

    # --- 属性 ---

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """沙箱名称（唯一标识符）。"""

    # --- 生命周期 ---

    @abc.abstractmethod
    async def stop(self) -> None:
        """停止沙箱，保留其状态。"""

    @abc.abstractmethod
    async def info(self) -> SandboxInfo:
        """获取沙箱状态信息。"""

    # --- 执行 ---

    @abc.abstractmethod
    async def exec(
        self,
        command: str,
        *args: str,
        env: Optional[dict[str, str]] = None,
    ) -> ExecResult:
        """在沙箱中执行 Shell 命令。

        Args:
            command: 要执行的 Shell 命令。
            args: 命令参数。
            env: 额外的环境变量（与已有环境合并）。

        Returns:
            ExecResult: 包含退出码、stdout 和 stderr 的执行结果。
        """

    @abc.abstractmethod
    async def run_code(
        self,
        code: str,
        code_type: CodeType = "python",
        env: Optional[dict[str, str]] = None,
    ) -> ExecResult:
        """在沙箱中执行代码。

        Args:
            code: 要执行的代码字符串。
            code_type: 代码类型。
            env: 额外的环境变量（与已有环境合并）。

        Returns:
            ExecResult: 包含退出码、stdout 和 stderr 的执行结果。
        """

    # --- 文件操作 ---

    @abc.abstractmethod
    async def upload_file(
        self, local_path: str, remote_path: str, overwrite: bool = False
    ) -> None:
        """将本地文件上传到沙箱。

        Args:
            local_path: 本地文件路径。
            remote_path: 沙箱中的目标路径（含文件名）。
            overwrite: 如果目标已存在是否覆盖。默认 False。

        Raises:
            FileNotFoundError: 本地文件未找到。
            FileExistsError: 目标已存在且 overwrite=False。
        """

    @abc.abstractmethod
    async def download_file(
        self, remote_path: str, local_path: str, overwrite: bool = False
    ) -> None:
        """从沙箱下载文件。

        Args:
            remote_path: 沙箱中的源文件路径。
            local_path: 本地目标路径（含文件名）。
            overwrite: 如果本地文件已存在是否覆盖。默认 False。

        Raises:
            FileNotFoundError: 沙箱中源文件未找到。
            FileExistsError: 本地文件已存在且 overwrite=False。
        """

    @abc.abstractmethod
    async def write_file(
        self, content: str, remote_path: str, overwrite: bool = False
    ) -> None:
        """将字符串内容直接写入沙箱文件。

        Args:
            content: 要写入的文本内容。
            remote_path: 沙箱中的目标路径（含文件名）。
            overwrite: 如果目标已存在是否覆盖。默认 False。

        Raises:
            FileExistsError: 目标已存在且 overwrite=False。
        """

    @abc.abstractmethod
    async def read_file(self, remote_path: str) -> str:
        """从沙箱中读取文件内容。

        Args:
            remote_path: 沙箱中的文件路径。

        Raises:
            FileNotFoundError: 沙箱中文件未找到。
        """


class SandboxService(abc.ABC):
    """
    沙箱生命周期管理抽象接口。

    典型用法：

        service = BoxliteService()

        # 获取或创建沙箱
        async with await service.get_or_create("my-box") as sandbox:
            result = await sandbox.exec("python train.py")
            print(sandbox.name)  # "my-box"

        # 列出所有沙箱
        boxes = await service.list_sandboxes()
        print(boxes)

        # 删除沙箱
        await service.delete("my-box")

        # 创建快照
        await service.create_snapshot("my-box", "my-box-v1.0")

        # 从快照创建
        await service.get_or_create("my-box", template=SandboxTemplate(_type="snapshot", snapshot_id="my-box-v1.0"))
    """

    @abc.abstractmethod
    async def get_or_create(
        self,
        name: str,
        template: Optional[SandboxTemplate] = None,
        config: Optional[SandboxConfig] = None,
    ) -> Sandbox:
        """获取或创建沙箱，自动处理恢复逻辑。

        行为规则：
        - 已存在且运行中 → 直接返回
        - 已存在但已停止 → 恢复后返回
        - 不存在 → 创建后返回

        Args:
            name: 沙箱名称（唯一标识符）。
            template: 仅在创建时使用的模板。对已有沙箱忽略。
            config: 仅在创建时使用的配置。对已有沙箱忽略。

        Returns:
            Sandbox: 可操作的沙箱实例。
        """

    @abc.abstractmethod
    async def list_sandboxes(self) -> list[SandboxInfo]:
        """列出所有沙箱（包括运行中和已停止的）。

        Returns:
            list[SandboxInfo]: 沙箱状态信息列表。
        """

    @abc.abstractmethod
    async def delete(self, name: str) -> None:
        """永久删除沙箱并释放所有资源。

        Args:
            name: 要删除的沙箱名称。
        """

    @abc.abstractmethod
    async def supports_snapshots(self) -> bool:
        """检查此沙箱服务是否支持快照操作。

        Returns:
            bool: 支持快照返回 True，否则返回 False。
        """

    @abc.abstractmethod
    async def create_snapshot(self, name: str, snapshot_id: str) -> SandboxSnapshot:
        """创建沙箱快照。

        Args:
            name: 沙箱名称。
            snapshot_id: 唯一快照标识符。
        """

    @abc.abstractmethod
    async def list_snapshots(self) -> list[SandboxSnapshot]:
        """列出所有沙箱快照。

        Returns:
            list[SandboxSnapshot]: 快照信息列表。
        """

    @abc.abstractmethod
    async def delete_snapshot(self, snapshot_id: str) -> None:
        """永久删除沙箱快照。

        Args:
            snapshot_id: 唯一快照标识符。
        """
