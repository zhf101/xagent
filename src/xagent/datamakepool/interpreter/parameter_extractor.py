"""Datamakepool 参数提取器。

该模块只做“模板匹配前的最小参数预解析”，不追求完整 NLU。
当前刻意保持简单，目的是先为模板匹配和执行规划提供几个高价值信号：

- `system_short`
- `count`
- `entity_type`

复杂实体识别、槽位补全、歧义消解后续可以继续演进到 LLM 或规则混合方案。
"""

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
    """从自然语言中提取模板匹配与执行规划需要的最小参数集合。

    输出语义：
    - 只返回当前已稳定支持的字段
    - 提取失败时返回空字典，而不是抛异常

    这样上层 matcher / planner 可以把它当成一个“尽力而为”的弱信号来源。
    """

    normalized = text.strip()
    lowered = normalized.lower()
    result: Dict[str, Any] = {}

    # system_short 是模板匹配最强信号之一，先做早停提取。
    for system in _SYSTEMS:
        if system in lowered:
            result["system_short"] = system
            break

    # 数量字段供模板参数注入使用，当前只取第一处显式数字。
    count_match = re.search(r"(\d+)\s*(个|条|张|笔|套)?", normalized)
    if count_match:
        try:
            result["count"] = int(count_match.group(1))
        except ValueError:
            pass

    # entity_type 主要影响模板召回和 SQL / HTTP 资产语义对齐。
    for entity_type, keywords in _ENTITY_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            result["entity_type"] = entity_type
            break

    return result
