"""
Shell 命令安全预检。

首版重点解决两类问题：
- 明显网络探测命令
- 命令里显式出现的 URL 指向受阻目标
"""

from __future__ import annotations

from pathlib import Path
import re

from .models import SafetyDecision, SafetyEvidence
from .network_guard import NetworkSafetyGuard
from .policy import AgentSafetyPolicy

_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_ABS_PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/][^\s'\"<>|&;]+)|(?:/(?!/)[^\s'\"<>|&;]+))"
)


class ShellSafetyGuard:
    """对 shell 命令做技术安全预检。"""

    def __init__(
        self,
        policy: AgentSafetyPolicy | None = None,
        network_guard: NetworkSafetyGuard | None = None,
    ) -> None:
        self.policy = policy or AgentSafetyPolicy()
        self.network_guard = network_guard or NetworkSafetyGuard(self.policy)

    def evaluate_command(
        self,
        command: str,
        workspace_root: str | None = None,
    ) -> SafetyDecision:
        """
        检查命令中是否存在明显的探测、破坏性行为或 workspace 逃逸。

        `workspace_root` 只表达技术沙箱根目录，不表达业务权限。
        """

        for pattern in self.policy.blocked_command_patterns:
            if re.search(pattern, command, flags=re.IGNORECASE):
                return SafetyDecision(
                    status="block",
                    evidences=[
                        SafetyEvidence(
                            code="blocked_command_pattern",
                            message=f"命令命中高风险模式: {pattern}",
                            target=command,
                        )
                    ],
                )

        for url in _URL_PATTERN.findall(command):
            decision = self.network_guard.evaluate_url(url)
            if not decision.allowed:
                return decision

        if workspace_root:
            workspace_decision = self._evaluate_workspace_boundary(
                command=command,
                workspace_root=workspace_root,
            )
            if not workspace_decision.allowed:
                return workspace_decision

        return SafetyDecision(status="allow")

    def _evaluate_workspace_boundary(
        self,
        command: str,
        workspace_root: str,
    ) -> SafetyDecision:
        """
        对 shell 命令做轻量 workspace 边界检查。

        这里不尝试完整解析 shell AST，而是拦截最常见、最危险的逃逸信号：
        - `../` / `..\\` 路径遍历
        - 指向 workspace 根目录外的绝对路径
        """

        normalized_command = command.replace("\\\\", "\\")
        if re.search(r"(^|[\s'\"=])\.\.(?:[\\/]|$)", normalized_command):
            return SafetyDecision(
                status="block",
                evidences=[
                    SafetyEvidence(
                        code="blocked_path_traversal",
                        message="命令包含路径遍历 '..'，可能逃逸 workspace 边界",
                        target=command,
                    )
                ],
            )

        workspace_path = Path(workspace_root).resolve()
        for matched in _ABS_PATH_PATTERN.finditer(command):
            raw_path = matched.group("path")
            if not raw_path or "://" in raw_path or raw_path.startswith("//"):
                continue

            try:
                candidate = Path(raw_path).resolve()
            except Exception:
                continue

            if candidate == workspace_path or candidate.is_relative_to(workspace_path):
                continue

            return SafetyDecision(
                status="block",
                evidences=[
                    SafetyEvidence(
                        code="blocked_workspace_escape",
                        message=(
                            f"命令引用了 workspace 外绝对路径 '{raw_path}'，"
                            "当前执行不允许突破工作区边界"
                        ),
                        target=command,
                    )
                ],
            )

        return SafetyDecision(status="allow")
