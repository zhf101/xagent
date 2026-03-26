"""Parameter extraction for datamakepool prompts."""

from __future__ import annotations

import re
from typing import Any, Dict


_SYSTEMS = ("crm", "oms", "wms", "tms", "card", "cms")
_ENTITY_KEYWORDS = {
    "user": ("用户", "user"),
    "order": ("订单", "order"),
    "return_order": ("退货单", "退货", "return"),
    "card": ("借记卡", "卡bin", "卡", "card", "bin"),
}


def extract_parameters(text: str) -> Dict[str, Any]:
    """从自然语言中提取模板匹配和执行需要的最小参数集合。"""
    normalized = text.strip()
    lowered = normalized.lower()
    result: Dict[str, Any] = {}

    for system in _SYSTEMS:
        if system in lowered:
            result["system_short"] = system
            break

    count_match = re.search(r"(\d+)\s*(个|条|张|笔|套)?", normalized)
    if count_match:
        try:
            result["count"] = int(count_match.group(1))
        except ValueError:
            pass

    for entity_type, keywords in _ENTITY_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            result["entity_type"] = entity_type
            break

    return result
