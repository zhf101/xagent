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
        if self.workspace is None:
            raise ValueError("HTTP file download requires workspace support.")
        return self.workspace.resolve_path(f"{output_dir}/{filename}", default_dir="output")

    def register_download(self, file_path: Path) -> str:
        if self.workspace is None:
            raise ValueError("HTTP file download requires workspace support.")
        return self.workspace.register_file(str(file_path))

    @staticmethod
    def guess_mime_type(filename: str, fallback: str = "application/octet-stream") -> str:
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or fallback
