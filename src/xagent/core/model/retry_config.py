"""模型重试配置收口。

这个模块故意放在 `core.model` 顶层，而不是 `chat` 子包里，原因是：
1. `ModelConfig` 需要引用默认重试次数。
2. `chat` 相关适配器也需要同一套规则。
3. 如果把常量放在 `chat` 包内，`model.py` 导入时容易触发包级循环引用。
"""

DEFAULT_LLM_MAX_RETRIES = 3
MAX_LLM_MAX_RETRIES = 10


def normalize_llm_retry_count(max_retries: int | None) -> int:
    """统一收口 LLM 重试次数配置。

    约束说明：
    1. `None`、0、负数、无法解析的值，一律回退到项目默认值 3。
    2. 用户或数据库里配置得再高，也强制截断到 10，避免不可达时长时间空转。
    3. 这里只负责把数量规范化，不负责决定某类异常是否值得重试。
    """

    if max_retries is None:
        return DEFAULT_LLM_MAX_RETRIES

    try:
        normalized = int(max_retries)
    except (TypeError, ValueError):
        return DEFAULT_LLM_MAX_RETRIES

    if normalized <= 0:
        return DEFAULT_LLM_MAX_RETRIES

    return min(normalized, MAX_LLM_MAX_RETRIES)
