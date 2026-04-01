"""
通用 Agent 技术安全策略。

注意：
- 这里只表达 web / shell / 文件访问这类技术层风险
- 不替代 datamake 的业务审批和风险治理
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentSafetyPolicy(BaseModel):
    """技术安全策略集合。"""

    allowed_schemes: list[str] = Field(
        default_factory=lambda: ["http", "https"], description="允许的 URL 协议。"
    )
    blocked_hostnames: list[str] = Field(
        default_factory=lambda: [
            "localhost",
            "metadata.google.internal",
            "metadata",
        ],
        description="禁止访问的主机名黑名单。",
    )
    blocked_ip_literals: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"],
        description="禁止直接访问的 IP 常量。",
    )
    blocked_networks: list[str] = Field(
        default_factory=lambda: [
            "0.0.0.0/8",
            "10.0.0.0/8",
            "100.64.0.0/10",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "::1/128",
            "fc00::/7",
            "fe80::/10",
        ],
        description="显式阻断的网络段，覆盖私网、loopback、link-local 与 metadata 常见入口。",
    )
    blocked_command_patterns: list[str] = Field(
        default_factory=lambda: [
            r"\bnmap\b",
            r"\bnetcat\b",
            r"\bnc\b\s+-z",
            r"\btelnet\b",
            r"\brm\s+-[rf]{1,2}\b",
            r"\bdel\s+/[fq]\b",
            r"\brmdir\s+/s\b",
            r"\b(mkfs|diskpart)\b",
            r"\bdd\s+if=",
            r">\s*/dev/sd",
            r"\b(shutdown|reboot|poweroff)\b",
            r":\(\)\s*\{.*\};\s*:",
        ],
        description="明显网络探测、破坏性执行与系统级危险命令模式。",
    )
