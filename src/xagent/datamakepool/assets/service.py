"""Datamakepool 资产解析服务。

这里的“解析”不是执行资产，而是把外部请求意图映射到平台里已登记的资产定义。
它承担的是 resolver 职责，目标是给后续执行层一个稳定、可解释的匹配结果：

- HTTP：根据 method + 归一化 path 匹配
- SQL：根据任务描述中的关键词、标签、表名做轻量打分
- Dubbo：根据接口名 + 方法名精确匹配

当前策略刻意偏确定性，先保证行为可解释，后续再考虑更复杂的召回与排序。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .repositories import DubboAssetRepository, HttpAssetRepository, SqlAssetRepository


@dataclass
class HttpAssetMatchResult:
    """HTTP 资产解析结果。"""

    matched: bool
    asset_id: int | None = None
    asset_name: str | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None


class HttpAssetResolverService:
    """HTTP 资产解析服务。"""

    def __init__(self, repository: HttpAssetRepository):
        self.repository = repository

    def resolve(
        self,
        *,
        system_short: str | None,
        method: str,
        url: str,
    ) -> HttpAssetMatchResult:
        """按 method + path 匹配已激活的 HTTP 资产。

        关键约束：
        - 当前只比较 method 与 URL path，不比较 query string
        - 必须命中 active 资产，避免草稿/停用配置参与运行时路由
        """

        assets = self.repository.list_active_http_assets(system_short=system_short)
        request_path = urlparse(url).path.rstrip("/") or "/"
        request_method = method.upper()

        for asset in assets:
            config = asset.config or {}
            asset_method = str(config.get("method") or "").upper()
            base_url = str(config.get("base_url") or "").rstrip("/")
            path_template = str(config.get("path_template") or "").rstrip("/") or "/"
            if asset_method and asset_method != request_method:
                continue
            if not base_url:
                continue
            expected_path = urlparse(f"{base_url}{path_template}").path.rstrip("/") or "/"
            if expected_path == request_path:
                return HttpAssetMatchResult(
                    matched=True,
                    asset_id=asset.id,
                    asset_name=asset.name,
                    config=config,
                    reason=f"matched active HTTP asset '{asset.name}'",
                )

        return HttpAssetMatchResult(
            matched=False,
            reason="no active HTTP asset matched",
        )


@dataclass
class SqlAssetMatchResult:
    """SQL 资产解析结果。"""

    matched: bool
    asset_id: int | None = None
    asset_name: str | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None


class SqlAssetResolverService:
    """SQL 资产解析服务。"""

    def __init__(self, repository: SqlAssetRepository):
        self.repository = repository

    def resolve(
        self,
        *,
        task: str,
        system_short: str | None = None,
    ) -> SqlAssetMatchResult:
        """根据任务描述匹配 SQL 资产。

        当前使用轻量启发式打分：
        - tag 命中权重最高
        - 表名、资产名、sql_kind 次之
        - description 只做弱补充，不作为强信号

        该方法只返回“当前最像的一个资产”，不负责多候选排序暴露。
        """

        assets = self.repository.list_active_sql_assets(system_short=system_short)
        task_lower = task.lower()
        best: SqlAssetMatchResult | None = None
        best_score = 0.0

        for asset in assets:
            config = asset.config or {}
            tags = [str(t).lower() for t in (config.get("tags") or [])]
            table_names = [str(t).lower() for t in (config.get("table_names") or [])]
            sql_kind = str(config.get("sql_kind") or "").lower()
            name_lower = asset.name.lower() if asset.name else ""
            desc_lower = (asset.description or "").lower()
            score = 0.0
            if any(tag and tag in task_lower for tag in tags):
                score += 0.45
            if any(table and table in task_lower for table in table_names):
                score += 0.25
            if name_lower and name_lower in task_lower:
                score += 0.2
            if sql_kind and sql_kind in task_lower:
                score += 0.15
            if desc_lower and any(
                word in task_lower for word in desc_lower.split() if len(word) > 3
            ):
                score += 0.08

            if score > best_score:
                best_score = score
                best = SqlAssetMatchResult(
                    matched=True,
                    asset_id=asset.id,
                    asset_name=asset.name,
                    config=config,
                    reason=f"matched active SQL asset '{asset.name}' with score={score:.2f}",
                )

        if best is not None and best_score >= 0.2:
            return best

        return SqlAssetMatchResult(matched=False, reason="no active SQL asset matched")


@dataclass
class DubboAssetMatchResult:
    """Dubbo 资产解析结果。"""

    matched: bool
    asset_id: int | None = None
    asset_name: str | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None


class DubboAssetResolverService:
    """Dubbo 资产解析服务。"""

    def __init__(self, repository: DubboAssetRepository):
        self.repository = repository

    def resolve(
        self,
        *,
        system_short: str | None,
        service_interface: str,
        method_name: str,
    ) -> DubboAssetMatchResult:
        """按接口名 + 方法名精确匹配 Dubbo 资产。"""

        assets = self.repository.list_active_dubbo_assets(system_short=system_short)
        service_interface = service_interface.strip()
        method_name = method_name.strip()

        for asset in assets:
            config = asset.config or {}
            asset_interface = str(config.get("service_interface") or "").strip()
            asset_method = str(config.get("method_name") or "").strip()
            if asset_interface != service_interface:
                continue
            if asset_method != method_name:
                continue
            return DubboAssetMatchResult(
                matched=True,
                asset_id=asset.id,
                asset_name=asset.name,
                config=config,
                reason=f"matched active Dubbo asset '{asset.name}'",
            )

        return DubboAssetMatchResult(
            matched=False,
            reason="no active Dubbo asset matched",
        )
