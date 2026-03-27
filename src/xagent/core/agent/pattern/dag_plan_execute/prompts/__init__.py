"""DAG Plan-Execute 模式的 prompt 模板管理。

所有分类/规划阶段的 prompt 以 Markdown 文件存放在本目录下，
通过 `load_prompt()` 按名称加载，运行时拼接到 system prompt 中。

文件命名约定：
- classification_base.md        — 通用分类 prompt
- classification_{domain}.md    — 领域专属分类 prompt 补充片段

修改 .md 文件即可调优 prompt，无需改动 Python 代码。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# prompt 文件所在目录
_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """加载指定名称的 prompt 模板文件。

    Args:
        name: 文件名（不含 .md 后缀），如 "classification_base"

    Returns:
        文件内容字符串。若文件不存在则返回空字符串并记录警告。
    """
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        logger.warning(f"[load_prompt] Prompt 文件不存在: {path}")
        return ""
    text = path.read_text(encoding="utf-8")
    logger.debug(f"[load_prompt] 已加载 prompt: {name} ({len(text)} chars)")
    return text
