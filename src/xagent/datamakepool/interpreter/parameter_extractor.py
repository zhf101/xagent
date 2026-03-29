"""Datamakepool 参数提取器。

该模块只做“模板匹配前的最小参数预解析”，不追求完整 NLU。
当前刻意保持简单，目的是先为模板匹配和执行规划提供几个高价值信号：

- `system_short`
- `count`
- `entity_type`

复杂实体识别、槽位补全、歧义消解后续可以继续演进到 LLM 或规则混合方案。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

from xagent.core.observability.local_logging import log_dataflow

logger = logging.getLogger(__name__)


_SYSTEMS = ("crm", "oms", "wms", "tms", "card", "cms")
_ENTITY_KEYWORDS = {
    "user": ("用户", "user"),
    "order": ("订单", "order"),
    "return_order": ("退货单", "退货", "return"),
    "card": ("借记卡", "卡bin", "卡", "card", "bin"),
}
_COUNT_PATTERNS = (
    re.compile(r"(?<![A-Za-z])(\d+)\s*(个|条|张|笔|套|份|行|批)(?![A-Za-z])"),
    re.compile(r"(?:生成|造|创建|新增|插入|准备|产出|做)\s*(\d+)(?![A-Za-z0-9])"),
)


def _extract_count(text: str) -> int | None:
    """提取数量信息。

    约束：
    - 不能把 `YD03`、`UAT01` 这类环境编码里的数字误判成数量
    - 优先识别“数字 + 量词”或“动词 + 数字”这两类更稳定的数量表达
    """

    for pattern in _COUNT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            continue
    return None


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

    # 数量字段供模板参数注入使用，但不能误伤环境编码、系统编号等业务标识。
    count = _extract_count(normalized)
    if count is not None:
        result["count"] = count

    # entity_type 主要影响模板召回和 SQL / HTTP 资产语义对齐。
    for entity_type, keywords in _ENTITY_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            result["entity_type"] = entity_type
            break

    log_dataflow(
        logger,
        event="parameters_extracted",
        msg="已提取模板匹配参数",
        text_summary=normalized,
        params=result,
    )
    return result
