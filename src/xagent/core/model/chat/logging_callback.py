"""LLM 请求响应日志记录 Callback Handler

用于记录 LangChain LLM 调用的完整请求和响应信息，便于调试和监控。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)


class LLMRequestResponseLogger(BaseCallbackHandler):
    """记录 LLM 完整请求和响应的 Callback Handler
    
    该 Handler 会在 LLM 调用的各个阶段记录详细信息：
    - 请求开始：记录模型配置、输入 prompts、调用参数
    - 请求结束：记录完整响应内容、token 使用情况
    - 请求出错：记录错误信息
    
    使用方式：
        handler = LLMRequestResponseLogger()
        model = ChatOpenAI(callbacks=[handler])
    """
    
    def __init__(self, log_level: int = logging.DEBUG):
        """初始化日志记录器
        
        Args:
            log_level: 日志级别，默认为 DEBUG
        """
        super().__init__()
        self.log_level = log_level
        self._call_counter = 0
    
    def on_llm_start(
        self, 
        serialized: Dict[str, Any], 
        prompts: List[str], 
        **kwargs: Any
    ) -> None:
        """LLM 调用开始时触发，记录请求信息
        
        Args:
            serialized: 序列化的模型配置信息
            prompts: 输入的 prompt 列表
            **kwargs: 额外的调用参数（如 invocation_params）
        """
        self._call_counter += 1
        call_id = self._call_counter
        
        logger.log(self.log_level, "=" * 100)
        logger.log(self.log_level, f"[LLM 请求 #{call_id}] 开始")
        logger.log(self.log_level, "-" * 100)
        
        # 记录模型配置
        logger.log(
            self.log_level, 
            f"[模型配置]\n{json.dumps(serialized, ensure_ascii=False, indent=2)}"
        )
        
        # 记录输入 prompts
        logger.log(self.log_level, f"[输入 Prompts 数量] {len(prompts)}")
        for i, prompt in enumerate(prompts):
            logger.log(self.log_level, f"[Prompt {i+1}]\n{prompt}")
        
        # 记录调用参数（包含 temperature, max_tokens 等）
        if "invocation_params" in kwargs:
            logger.log(
                self.log_level,
                f"[调用参数]\n{json.dumps(kwargs['invocation_params'], ensure_ascii=False, indent=2)}"
            )
        
        # 记录其他额外参数
        other_params = {k: v for k, v in kwargs.items() if k != "invocation_params"}
        if other_params:
            logger.log(
                self.log_level,
                f"[额外参数]\n{json.dumps(str(other_params), ensure_ascii=False, indent=2)}"
            )
    
    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """LLM 调用结束时触发，记录响应信息
        
        Args:
            response: LLM 返回的结果对象
            **kwargs: 额外参数
        """
        logger.log(self.log_level, "-" * 100)
        logger.log(self.log_level, f"[LLM 响应 #{self._call_counter}]")
        
        # 记录生成的文本内容
        if response.generations:
            logger.log(self.log_level, f"[生成结果数量] {len(response.generations)}")
            for i, generation_list in enumerate(response.generations):
                logger.log(self.log_level, f"[生成组 {i+1}] 包含 {len(generation_list)} 个结果")
                for j, generation in enumerate(generation_list):
                    logger.log(self.log_level, f"  [结果 {j+1}] {generation.text}")
                    if generation.message:
                        logger.log(
                            self.log_level, 
                            f"  [消息内容] {generation.message.content}"
                        )
        
        # 记录 token 使用情况
        if response.llm_output:
            logger.log(
                self.log_level,
                f"[LLM 输出信息]\n{json.dumps(response.llm_output, ensure_ascii=False, indent=2)}"
            )
            
            # 特别突出 token 使用情况
            if "token_usage" in response.llm_output:
                token_usage = response.llm_output["token_usage"]
                logger.log(self.log_level, f"[Token 使用]")
                logger.log(self.log_level, f"  - 输入 tokens: {token_usage.get('prompt_tokens', 'N/A')}")
                logger.log(self.log_level, f"  - 输出 tokens: {token_usage.get('completion_tokens', 'N/A')}")
                logger.log(self.log_level, f"  - 总计 tokens: {token_usage.get('total_tokens', 'N/A')}")
        
        logger.log(self.log_level, "=" * 100)
    
    def on_llm_error(
        self, 
        error: Exception, 
        **kwargs: Any
    ) -> None:
        """LLM 调用出错时触发，记录错误信息
        
        Args:
            error: 异常对象
            **kwargs: 额外参数
        """
        logger.log(self.log_level, "-" * 100)
        logger.error(f"[LLM 调用错误 #{self._call_counter}]")
        logger.error(f"[错误类型] {type(error).__name__}")
        logger.error(f"[错误信息] {str(error)}")
        logger.log(self.log_level, "=" * 100)


class HTTPRequestLogger(BaseCallbackHandler):
    """记录底层 HTTP 请求的 Callback Handler
    
    注意：此 Handler 主要用于记录 LangChain 层面的信息，
    如需记录完整的 HTTP 请求/响应报文，建议配合 httpx/httpcore 的日志。
    """
    
    def on_llm_start(
        self, 
        serialized: Dict[str, Any], 
        prompts: List[str], 
        **kwargs: Any
    ) -> None:
        """记录即将发送的 HTTP 请求信息"""
        if "invocation_params" in kwargs:
            params = kwargs["invocation_params"]
            logger.debug(f"[HTTP 请求参数] {json.dumps(params, ensure_ascii=False, indent=2)}")


def enable_llm_request_logging(log_level: int = logging.DEBUG) -> LLMRequestResponseLogger:
    """启用 LLM 请求日志记录
    
    便捷函数，用于创建并返回日志记录 handler。
    
    Args:
        log_level: 日志级别
        
    Returns:
        配置好的 LLMRequestResponseLogger 实例
        
    使用示例：
        handler = enable_llm_request_logging()
        model = ChatOpenAI(callbacks=[handler])
    """
    return LLMRequestResponseLogger(log_level=log_level)


def configure_http_logging(enable: bool = True, level: int = logging.DEBUG) -> None:
    """配置底层 HTTP 客户端的日志记录
    
    启用后可以看到完整的 HTTP 请求和响应报文。
    
    Args:
        enable: 是否启用 HTTP 日志
        level: 日志级别
        
    注意：
        - OpenAI SDK 使用 httpx 作为 HTTP 客户端
        - 启用 httpx 和 httpcore 的 DEBUG 日志可以看到完整的请求/响应
    """
    if enable:
        # 配置 httpx 和 httpcore 的日志级别
        logging.getLogger("httpx").setLevel(level)
        logging.getLogger("httpcore").setLevel(level)
        logging.getLogger("openai").setLevel(level)
        logging.getLogger("langchain").setLevel(level)
        
        logger.info("已启用 HTTP 请求日志记录")
    else:
        # 恢复默认日志级别
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)
        logging.getLogger("langchain").setLevel(logging.INFO)
        
        logger.info("已禁用 HTTP 请求日志记录")
