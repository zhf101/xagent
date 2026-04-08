"""LLM 专用异常定义。

这个模块只处理“模型调用层”的异常语义，不关心具体是 OpenAI、代理网关还是别的
兼容端点。这样做的目的是把底层 SDK 的异常细节与上层 Agent 执行策略解耦：

1. 适配器负责把底层网络/超时/限流错误翻译成统一异常。
2. 重试包装器只关心“这个异常是否可重试”。
3. ReAct 等上层模式只关心“遇到这种异常时应该继续当前流程，还是直接友好失败”。
"""


class LLMRetryableError(RuntimeError):
    """Base exception for LLM errors that should trigger retry.

    This exception is used for transient LLM errors that may succeed on retry,
    such as:
    - Empty content responses
    - Invalid API responses
    - Timeout errors
    - Rate limit errors (429)
    - Server errors (5xx)

    Subclass this exception for specific retryable error types.
    """

    pass


class LLMEmptyContentError(LLMRetryableError):
    """Raised when LLM returns empty content with no tool calls.

    This is a transient error that may occur due to:
    - API temporary issues
    - Rate limiting
    - Network glitches
    - Model-specific behavior

    The request should be retried.
    """

    pass


class LLMInvalidResponseError(LLMRetryableError):
    """Raised when LLM response cannot be parsed or is invalid.

    This includes:
    - Malformed JSON responses
    - Missing required fields
    - Unexpected response structure
    - Cannot decode response

    The request should be retried.
    """

    pass


class LLMTimeoutError(LLMRetryableError):
    """Raised when LLM request times out.

    This includes:
    - First token timeout (no response within configured time)
    - Token interval timeout (gap between tokens exceeds configured time)
    - Network timeout

    The request should be retried.
    """

    pass


class LLMServiceUnavailableError(LLMRetryableError):
    """表示模型服务当前不可达，适合向前端直接展示友好提示。

    这个异常用于承接“网络不可达、网关不可达、服务端临时不可用”这类问题。
    之所以继承 `LLMRetryableError`，是因为单次调用内部仍然允许按既定策略重试；
    但一旦重试次数耗尽，上层执行器应该把它视为“本轮已经没有继续空转的意义”。
    """

    default_message = (
        "大模型服务暂时不可达，已多次重试仍失败。请检查模型地址、网络连通性或稍后再试。"
    )

    def __init__(self, message: str | None = None, *, detail: str | None = None):
        super().__init__(message or self.default_message)
        self.detail = detail


class LLMRequestTimeoutError(LLMServiceUnavailableError):
    """表示模型服务超时。

    超时本质上仍然属于“服务暂不可用”范畴，因此继承自
    `LLMServiceUnavailableError`。这样 ReAct 只需要识别一类异常，就能在
    服务不可达和超时两种场景下统一终止外层无意义重试。
    """

    default_message = (
        "大模型服务响应超时，已多次重试仍失败。请稍后再试，或检查模型服务状态。"
    )
