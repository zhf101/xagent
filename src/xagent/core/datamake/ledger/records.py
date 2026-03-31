"""
`Ledger Records`（账本记录辅助）模块。

这里集中放 datamake ledger 的最小记录类型与构造 helper，
避免后续 repository / projection / replay 直接散落硬编码字符串。
"""

from __future__ import annotations

from typing import Any, TypedDict


class LedgerRecordPayload(TypedDict):
    """
    `LedgerRecordPayload`（账本记录载荷）。

    当前只约束最小共性字段，保持对现有 domain payload 的透传。
    """

    record_type: str
    task_id: str
    round_id: int
    payload_json: dict[str, Any]


def build_ledger_record_payload(
    *,
    record_type: str,
    task_id: str,
    round_id: int,
    payload_json: dict[str, Any],
) -> LedgerRecordPayload:
    """
    构造统一 ledger record 载荷。
    """

    return {
        "record_type": record_type,
        "task_id": task_id,
        "round_id": round_id,
        "payload_json": payload_json,
    }
