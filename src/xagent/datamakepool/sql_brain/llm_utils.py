"""SQL Brain 里复用的轻量 LLM 辅助函数。"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any


def run_async_sync(coro: Any) -> Any:
    """把异步调用包装成同步接口。

    SQL Brain 当前仍以同步服务形态暴露给 datamakepool 工具链，
    因此这里统一处理“同步代码里调用异步 LLM / adapter”的场景。
    """

    result: Any = None
    error: Exception | None = None

    def target() -> None:
        nonlocal result, error
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            loop.close()
        except Exception as exc:  # pragma: no cover - 线程内异常转抛
            error = exc

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop and running_loop.is_running():
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
    else:
        return asyncio.run(coro)

    if error:
        raise error
    return result


def extract_sql_from_text(text: str) -> str:
    """从模型响应里尽量抽出 SQL 片段。"""

    patterns = [
        r"```sql\s*(.*?)```",
        r"```\s*(.*?)```",
        r"\bWITH\b .*?;",
        r"\bSELECT\b .*?;",
        r"\bINSERT\b .*?;",
        r"\bUPDATE\b .*?;",
        r"\bDELETE\b .*?;",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
        if matches:
            candidate = matches[-1]
            return candidate.strip()
    return text.strip()
