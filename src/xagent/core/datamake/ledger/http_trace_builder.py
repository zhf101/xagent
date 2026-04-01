"""
`HTTP Trace Builder`（HTTP 执行轨迹构建器）。

职责边界：
1. 把 HTTP 执行结果整理成 Ledger / UI 友好的稳定结构
2. 统一 observation / evidence / 审计视图中的 HTTP 字段口径

它不负责重新判断成功失败，也不回头改写 Runtime 结果。
"""

from __future__ import annotations

from typing import Any

from ..contracts.runtime import RuntimeResult


class HttpExecutionTraceBuilder:
    """
    `HttpExecutionTraceBuilder`（HTTP 执行轨迹构建器）。

    UI 和调试面板不应再直接从原始 `raw_result` 猜 HTTP 语义，
    而应统一消费这里整理后的结构。
    """

    def build(self, runtime_result: RuntimeResult) -> dict[str, Any]:
        """把 RuntimeResult 折叠成 HTTP 友好的审计结构。"""

        facts = dict(runtime_result.facts)
        data = dict(runtime_result.data)
        snapshot = data.get("http_execution_snapshot", {})
        if not isinstance(snapshot, dict):
            snapshot = {}

        return {
            "summary": runtime_result.summary,
            "status": runtime_result.status,
            "error": runtime_result.error,
            "transport_status": facts.get("transport_status"),
            "protocol_status": facts.get("protocol_status"),
            "business_status": facts.get("business_status"),
            "http_status": facts.get("http_status"),
            "business_error": facts.get("business_error"),
            "extracted_data": facts.get("extracted_data") or {},
            "request": snapshot.get("rendered_request") or {},
            "validated_args": snapshot.get("validated_args") or {},
            "evidence": list(runtime_result.evidence),
        }
