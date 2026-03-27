"""HTTP 文件桥接层。

负责把平台里的 `file_id` 映射成 workspace 里的实体文件，
以及把下载结果注册回平台文件系统。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from xagent.core.workspace import TaskWorkspace


class HttpFileBridge:
    """处理上传 / 下载与 workspace 的桥接。"""

    def __init__(self, workspace: TaskWorkspace | None):
        self.workspace = workspace

    def resolve_upload_file(self, file_id: str) -> Path:
        """把平台 file_id 解析为 workspace 中的真实文件路径。"""

        if self.workspace is None:
            raise ValueError("HTTP file upload requires workspace support.")

        resolved = self.workspace.resolve_file_id(file_id)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(f"Uploaded file not found for file_id={file_id}")
        return resolved

    def prepare_download_target(
        self,
        *,
        output_dir: str,
        filename: str,
    ) -> Path:
        """为下载文件分配 workspace 目标路径。

        这里只做路径解析，不做真正写文件。
        """

        if self.workspace is None:
            raise ValueError("HTTP file download requires workspace support.")
        return self.workspace.resolve_path(f"{output_dir}/{filename}", default_dir="output")

    def register_download(self, file_path: Path) -> str:
        """把下载结果注册回平台文件系统，返回新的 file_id。"""

        if self.workspace is None:
            raise ValueError("HTTP file download requires workspace support.")
        return self.workspace.register_file(str(file_path))

    @staticmethod
    def guess_mime_type(filename: str, fallback: str = "application/octet-stream") -> str:
        """按文件名推断 MIME；推断失败时回退为通用二进制类型。"""

        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or fallback
