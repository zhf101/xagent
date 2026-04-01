"""
`Template Embedding Resolver`（模板检索 embedding 解析器）模块。

这个模块专门负责把 datamake 模板检索所需的 embedding 服务
从全局 `.env` 配置解析成可直接使用的 `BaseEmbedding` 适配器。

设计边界：
- 这里只做“读取全局配置 -> 构造 embedding 适配器”。
- 不参与模板检索打分，不依赖用户级默认模型，不访问数据库。
- 若没有配置 datamake 专用 embedding，则返回 `None`，由上层回退到本地 hashed embedding。
"""

from __future__ import annotations

import os

from ...model.embedding.adapter import create_embedding_adapter
from ...model.embedding.base import BaseEmbedding
from ...model.model import EmbeddingModelConfig


def resolve_template_embedding_from_env() -> BaseEmbedding | None:
    """
    从全局环境变量解析 datamake 模板检索专用 embedding 适配器。

    配置策略：
    - 只认全局 `.env` 变量，不读取用户级默认 embedding。
    - 只在 `XAGENT_TEMPLATE_EMBEDDING_MODEL` 存在时启用。
    - provider 未显式配置时，默认按 `dashscope` 解析，兼容当前项目常见部署方式。

    约束：
    - 这里不吞掉“明确配置了 provider/model 但配置非法”的异常，
      这样环境配置错误能尽早暴露，而不是静默退回弱语义检索。
    """

    model_name = _read_first_non_empty("XAGENT_TEMPLATE_EMBEDDING_MODEL")
    if model_name is None:
        return None

    provider = (
        _read_first_non_empty("XAGENT_TEMPLATE_EMBEDDING_PROVIDER") or "dashscope"
    ).strip()
    base_url = _read_first_non_empty("XAGENT_TEMPLATE_EMBEDDING_BASE_URL")
    api_key = _resolve_api_key(provider)
    dimension = _read_optional_int("XAGENT_TEMPLATE_EMBEDDING_DIMENSION")

    config = EmbeddingModelConfig(
        id=f"datamake_template_embedding::{provider}::{model_name}",
        model_name=model_name,
        model_provider=provider,
        api_key=api_key,
        base_url=base_url,
        dimension=dimension,
    )
    return create_embedding_adapter(config)


def _resolve_api_key(provider: str) -> str | None:
    """
    按 provider 解析 datamake 模板 embedding 所需的 API Key。

    优先级：
    1. `XAGENT_TEMPLATE_EMBEDDING_API_KEY`
    2. provider 对应的通用环境变量 fallback
    """

    explicit_key = _read_first_non_empty("XAGENT_TEMPLATE_EMBEDDING_API_KEY")
    if explicit_key is not None:
        return explicit_key

    normalized_provider = provider.strip().lower()
    if normalized_provider in {"openai", "openai_embedding"}:
        return _read_first_non_empty("OPENAI_API_KEY")
    if normalized_provider == "dashscope":
        return _read_first_non_empty("DASHSCOPE_API_KEY")
    if normalized_provider == "xinference":
        return _read_first_non_empty("XINFERENCE_API_KEY")
    return None


def _read_first_non_empty(*env_names: str) -> str | None:
    """
    读取第一个非空环境变量值。
    """

    for env_name in env_names:
        value = os.getenv(env_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_optional_int(env_name: str) -> int | None:
    """
    把可选整型环境变量解析成 `int | None`。
    """

    raw_value = _read_first_non_empty(env_name)
    if raw_value is None:
        return None
    return int(raw_value)
