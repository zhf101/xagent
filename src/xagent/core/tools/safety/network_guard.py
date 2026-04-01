"""
网络访问安全预检。

首版目标：
- 阻断 localhost / loopback / 私网 / metadata endpoint
- 阻断非法 scheme
- 为 web / API / 未来 MCP 网络访问提供统一入口
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from .models import SafetyDecision, SafetyEvidence
from .policy import AgentSafetyPolicy


class NetworkSafetyGuard:
    """统一的 URL / Host 技术安全预检。"""

    def __init__(self, policy: AgentSafetyPolicy | None = None) -> None:
        self.policy = policy or AgentSafetyPolicy()

    def evaluate_url(self, url: str) -> SafetyDecision:
        """
        对 URL 做技术安全预检。

        与首版静态 host 校验相比，这里额外补齐两层能力：
        - hostname 进入 DNS 解析后，对所有解析到的 IP 逐个校验
        - 重定向复检时复用同一套解析逻辑，避免“域名看起来安全，实际落到内网 IP”
        """

        try:
            parsed = urlparse(url)
        except Exception as exc:
            return self._block("invalid_url", f"URL 解析失败: {exc}", url)

        scheme = (parsed.scheme or "").lower()
        if scheme not in self.policy.allowed_schemes:
            return self._block(
                "blocked_scheme",
                f"URL scheme '{scheme or '<empty>'}' 不在允许列表中",
                url,
            )

        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return self._block("missing_hostname", "URL 缺少主机名", url)

        if hostname in {item.lower() for item in self.policy.blocked_hostnames}:
            return self._block(
                "blocked_hostname", f"主机名 '{hostname}' 被安全策略阻断", url
            )

        if hostname in {item.lower() for item in self.policy.blocked_ip_literals}:
            return self._block("blocked_ip", f"IP '{hostname}' 被安全策略阻断", url)

        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return self._evaluate_hostname_resolution(hostname, url)

        decision = self._evaluate_ip(ip, url)
        if not decision.allowed:
            return decision

        return SafetyDecision(status="allow")

    def evaluate_redirect_targets(self, urls: list[str]) -> SafetyDecision:
        """对重定向链路上的 URL 逐个复检。"""

        for url in urls:
            decision = self.evaluate_url(url)
            if not decision.allowed:
                return decision
        return SafetyDecision(status="allow")

    def _block(self, code: str, message: str, target: str) -> SafetyDecision:
        return SafetyDecision(
            status="block",
            evidences=[SafetyEvidence(code=code, message=message, target=target)],
        )

    def _evaluate_hostname_resolution(self, hostname: str, target_url: str) -> SafetyDecision:
        """
        对 hostname 做 DNS 解析，并校验每一个解析结果。

        设计原因：
        - 仅凭 hostname 字面值无法判断它最终是否会落到私网
        - 多 A/AAAA 记录场景中，只要有一个结果落入受阻网段，就应直接阻断
        """

        try:
            resolved_items = socket.getaddrinfo(
                hostname,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            return self._block(
                "dns_resolution_failed",
                f"主机名 '{hostname}' DNS 解析失败: {exc}",
                target_url,
            )
        except Exception as exc:  # pragma: no cover - 防御性兜底
            return self._block(
                "dns_resolution_failed",
                f"主机名 '{hostname}' 解析异常: {exc}",
                target_url,
            )

        checked_ips: set[str] = set()
        for item in resolved_items:
            sockaddr = item[4]
            if not sockaddr:
                continue
            ip_literal = str(sockaddr[0]).strip()
            if not ip_literal or ip_literal in checked_ips:
                continue
            checked_ips.add(ip_literal)

            try:
                ip = ipaddress.ip_address(ip_literal)
            except ValueError:
                continue

            decision = self._evaluate_ip(ip, target_url)
            if not decision.allowed:
                return SafetyDecision(
                    status="block",
                    evidences=[
                        SafetyEvidence(
                            code=decision.evidences[0].code,
                            message=(
                                f"主机名 '{hostname}' 解析到受阻地址 '{ip_literal}': "
                                f"{decision.evidences[0].message}"
                            ),
                            target=target_url,
                        )
                    ],
                )

        if not checked_ips:
            return self._block(
                "dns_resolution_failed",
                f"主机名 '{hostname}' 未解析出可检查的地址",
                target_url,
            )

        return SafetyDecision(status="allow")

    def _evaluate_ip(self, ip: ipaddress._BaseAddress, target_url: str) -> SafetyDecision:
        """
        对单个 IP 做黑名单与保留网段校验。

        这里优先使用显式 `blocked_networks`，同时保留 `ipaddress` 的通用保留段判断，
        避免仅依赖某一种分类方式导致漏拦。
        """

        for network_text in self.policy.blocked_networks:
            network = ipaddress.ip_network(network_text, strict=False)
            if ip in network:
                return self._block(
                    "blocked_private_network",
                    f"IP '{ip}' 命中受阻网段 '{network_text}'",
                    target_url,
                )

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return self._block(
                "blocked_private_network",
                f"IP '{ip}' 属于禁止访问的内部或保留网段",
                target_url,
            )

        return SafetyDecision(status="allow")
