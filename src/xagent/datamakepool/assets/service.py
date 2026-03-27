"""Datamakepool 资产解析服务。

这里的“解析”不是执行资产，而是把外部请求意图映射到平台里已登记的资产定义。
它承担的是 resolver 职责，目标是给后续执行层一个稳定、可解释的匹配结果：

- HTTP：根据 method + 归一化 path 匹配
- SQL：根据任务描述中的关键词、标签、表名做轻量打分
- Dubbo：根据接口名 + 方法名精确匹配

当前策略刻意偏确定性，先保证行为可解释，后续再考虑更复杂的召回与排序。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from xagent.datamakepool.recall_funnel import RecallFunnelExecutor, RecallQuery
from xagent.datamakepool.recall_funnel.adapters import (
    HttpAssetRecallAdapter,
    SqlAssetRecallAdapter,
)

from .repositories import DubboAssetRepository, HttpAssetRepository, SqlAssetRepository

if TYPE_CHECKING:
    from .http_asset_retriever import HttpAssetRetriever
    from .sql_asset_retriever import SqlAssetRetriever


@dataclass
class HttpAssetMatchResult:
    """HTTP 资产解析结果。"""

    matched: bool
    asset_id: int | None = None
    asset_name: str | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None
    fallback_candidates: list[dict[str, Any]] = field(default_factory=list)
    recall_strategy: str | None = None
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: list[dict[str, Any]] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)


class HttpAssetResolverService:
    """HTTP 资产解析服务。"""

    def __init__(
        self,
        repository: HttpAssetRepository,
        retriever: "HttpAssetRetriever | None" = None,
    ):
        self.repository = repository
        self._retriever = retriever

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

        query = RecallQuery(
            query_text=f"{method} {url}",
            system_short=system_short,
            top_k=20,
            context={"method": method, "url": url},
        )
        adapter = HttpAssetRecallAdapter(
            repository=self.repository,
            retriever=self._retriever,
        )
        execution = RecallFunnelExecutor[Any]().run(adapter, query)
        payload = adapter.finalize(query, execution.candidates)
        return HttpAssetMatchResult(
            matched=bool(payload.get("matched")),
            asset_id=payload.get("asset_id"),
            asset_name=payload.get("asset_name"),
            config=payload.get("config"),
            reason=payload.get("reason"),
            fallback_candidates=payload.get("fallback_candidates") or [],
            recall_strategy=execution.recall_strategy,
            used_ann=execution.used_ann,
            used_fallback=execution.used_fallback,
            stage_results=[stage.to_dict() for stage in execution.stage_results],
            score_breakdown=payload.get("score_breakdown") or {},
        )


@dataclass
class SqlAssetMatchResult:
    """SQL 资产解析结果。"""

    matched: bool
    asset_id: int | None = None
    asset_name: str | None = None
    config: dict[str, Any] | None = None
    reason: str | None = None
    score: float = 0.0
    matched_signals: list[str] | None = None
    candidate_count: int = 0
    top_candidates: list[dict[str, Any]] | None = None
    recall_strategy: str | None = None
    used_ann: bool = False
    used_fallback: bool = False
    stage_results: list[dict[str, Any]] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)


class SqlAssetResolverService:
    """SQL 资产解析服务。"""

    def __init__(
        self,
        repository: SqlAssetRepository,
        retriever: "SqlAssetRetriever | None" = None,
    ):
        self.repository = repository
        self._retriever = retriever

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

        query = RecallQuery(
            query_text=task,
            system_short=system_short,
            top_k=20,
        )
        adapter = SqlAssetRecallAdapter(
            repository=self.repository,
            retriever=self._retriever,
        )
        execution = RecallFunnelExecutor[Any]().run(adapter, query)
        payload = adapter.finalize(query, execution.candidates)
        return SqlAssetMatchResult(
            matched=bool(payload.get("matched")),
            asset_id=payload.get("asset_id"),
            asset_name=payload.get("asset_name"),
            config=payload.get("config"),
            reason=payload.get("reason"),
            score=float(payload.get("score") or 0.0),
            matched_signals=payload.get("matched_signals"),
            candidate_count=int(payload.get("candidate_count") or 0),
            top_candidates=payload.get("top_candidates"),
            recall_strategy=execution.recall_strategy,
            used_ann=execution.used_ann,
            used_fallback=execution.used_fallback,
            stage_results=[stage.to_dict() for stage in execution.stage_results],
            score_breakdown=payload.get("score_breakdown") or {},
        )


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
