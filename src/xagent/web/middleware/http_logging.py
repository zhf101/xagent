"""HTTP 请求响应日志记录中间件

记录所有 HTTP 接口的完整请求和响应报文到独立的日志文件。
"""

import json
import logging
import time
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message

# 创建专门的 HTTP 日志记录器，输出到独立文件
http_logger = logging.getLogger("xagent.http")


class HTTPLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求响应日志记录中间件
    
    功能：
    - 记录完整的请求信息（方法、路径、headers、query params、body）
    - 记录完整的响应信息（状态码、headers、body）
    - 记录请求处理时间
    - 自动过滤敏感信息（如 Authorization header）
    - 支持配置是否记录请求/响应 body
    
    使用方式：
        app.add_middleware(HTTPLoggingMiddleware, log_body=True)
    """
    
    def __init__(
        self,
        app,
        log_request_body: bool = True,
        log_response_body: bool = True,
        max_body_length: int = 10000,
        exclude_paths: Optional[list[str]] = None,
    ):
        """初始化 HTTP 日志中间件
        
        Args:
            app: FastAPI 应用实例
            log_request_body: 是否记录请求 body
            log_response_body: 是否记录响应 body
            max_body_length: body 最大记录长度（字节），超过则截断
            exclude_paths: 排除的路径列表（如健康检查接口）
        """
        super().__init__(app)
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_length = max_body_length
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json"]
        self._request_counter = 0
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理请求并记录日志"""
        # 检查是否需要排除此路径
        if self._should_exclude(request.url.path):
            return await call_next(request)
        
        # 生成请求 ID
        self._request_counter += 1
        request_id = self._request_counter
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 记录请求信息
        await self._log_request(request, request_id)
        
        # 处理请求并捕获响应
        response = await self._process_request(request, call_next)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应信息
        await self._log_response(response, request_id, process_time)
        
        return response
    
    def _should_exclude(self, path: str) -> bool:
        """判断路径是否应该被排除"""
        for exclude_path in self.exclude_paths:
            if path.startswith(exclude_path):
                return True
        return False
    
    async def _log_request(self, request: Request, request_id: int) -> None:
        """记录请求信息"""
        http_logger.info("=" * 100)
        http_logger.info(f"[HTTP 请求 #{request_id}]")
        http_logger.info("-" * 100)
        
        # 基本信息
        http_logger.info(f"[方法] {request.method}")
        http_logger.info(f"[路径] {request.url.path}")
        http_logger.info(f"[完整URL] {str(request.url)}")
        
        # Query 参数
        if request.query_params:
            http_logger.info(f"[Query 参数] {dict(request.query_params)}")
        
        # Headers（过滤敏感信息）
        headers = self._sanitize_headers(dict(request.headers))
        http_logger.info(f"[请求 Headers]")
        for key, value in headers.items():
            http_logger.info(f"  {key}: {value}")
        
        # 客户端信息
        if request.client:
            http_logger.info(f"[客户端] {request.client.host}:{request.client.port}")
        
        # 请求 Body
        if self.log_request_body and request.method in ["POST", "PUT", "PATCH"]:
            body = await self._read_request_body(request)
            if body:
                http_logger.info(f"[请求 Body]")
                http_logger.info(body)
    
    async def _process_request(
        self, request: Request, call_next: Callable
    ) -> Response:
        """处理请求并捕获响应 body"""
        # 保存原始的 body，因为读取后需要重新设置
        body = await request.body()
        
        async def receive() -> Message:
            return {"type": "http.request", "body": body}
        
        # 替换 receive 函数以便可以多次读取 body
        request._receive = receive
        
        # 调用下一个中间件/路由处理器
        response = await call_next(request)
        
        # 如果需要记录响应 body，需要读取并重新构造响应
        if self.log_response_body:
            response = await self._capture_response_body(response)
        
        return response
    
    async def _capture_response_body(self, response: Response) -> Response:
        """捕获响应 body"""
        # 读取响应 body
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk
        
        # 保存 body 到响应对象（用于后续日志记录）
        response.body_content = response_body
        
        # 重新构造响应的 body_iterator
        async def new_body_iterator():
            yield response_body
        
        response.body_iterator = new_body_iterator()
        
        return response
    
    async def _log_response(
        self, response: Response, request_id: int, process_time: float
    ) -> None:
        """记录响应信息"""
        http_logger.info("-" * 100)
        http_logger.info(f"[HTTP 响应 #{request_id}]")
        
        # 状态码
        http_logger.info(f"[状态码] {response.status_code}")
        
        # 处理时间
        http_logger.info(f"[处理时间] {process_time:.4f} 秒")
        
        # Headers
        http_logger.info(f"[响应 Headers]")
        for key, value in response.headers.items():
            http_logger.info(f"  {key}: {value}")
        
        # 响应 Body
        if self.log_response_body and hasattr(response, "body_content"):
            body_str = self._format_response_body(
                response.body_content, response.headers.get("content-type", "")
            )
            if body_str:
                http_logger.info(f"[响应 Body]")
                http_logger.info(body_str)
        
        http_logger.info("=" * 100)
        http_logger.info("")  # 空行分隔
    
    async def _read_request_body(self, request: Request) -> Optional[str]:
        """读取并格式化请求 body"""
        try:
            body = await request.body()
            if not body:
                return None
            
            # 尝试解析为 JSON
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    json_data = json.loads(body)
                    # 过滤敏感字段
                    json_data = self._sanitize_json(json_data)
                    return json.dumps(json_data, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            
            # 如果是文本类型，直接返回
            if any(
                t in content_type
                for t in ["text/", "application/x-www-form-urlencoded"]
            ):
                body_str = body.decode("utf-8", errors="replace")
                return self._truncate(body_str)
            
            # 二进制数据
            return f"<二进制数据，长度: {len(body)} 字节>"
        
        except Exception as e:
            return f"<读取 body 失败: {str(e)}>"
    
    def _format_response_body(self, body: bytes, content_type: str) -> Optional[str]:
        """格式化响应 body"""
        try:
            if not body:
                return None
            
            # JSON 响应
            if "application/json" in content_type:
                try:
                    json_data = json.loads(body)
                    # 过滤敏感字段
                    json_data = self._sanitize_json(json_data)
                    return json.dumps(json_data, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass
            
            # 文本响应
            if any(t in content_type for t in ["text/", "application/xml"]):
                body_str = body.decode("utf-8", errors="replace")
                return self._truncate(body_str)
            
            # 二进制数据
            return f"<二进制数据，长度: {len(body)} 字节>"
        
        except Exception as e:
            return f"<格式化响应失败: {str(e)}>"
    
    def _sanitize_headers(self, headers: dict) -> dict:
        """过滤敏感的 header 信息"""
        sensitive_keys = ["authorization", "cookie", "x-api-key", "api-key"]
        sanitized = {}
        
        for key, value in headers.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _sanitize_json(self, data: any) -> any:
        """递归过滤 JSON 中的敏感字段"""
        if isinstance(data, dict):
            sanitized = {}
            sensitive_keys = [
                "password",
                "token",
                "secret",
                "api_key",
                "apikey",
                "access_token",
                "refresh_token",
            ]
            
            for key, value in data.items():
                key_lower = key.lower()
                if any(sensitive in key_lower for sensitive in sensitive_keys):
                    sanitized[key] = "***REDACTED***"
                else:
                    sanitized[key] = self._sanitize_json(value)
            
            return sanitized
        
        elif isinstance(data, list):
            return [self._sanitize_json(item) for item in data]
        
        else:
            return data
    
    def _truncate(self, text: str) -> str:
        """截断过长的文本"""
        if len(text) <= self.max_body_length:
            return text
        
        return text[: self.max_body_length] + f"\n... <截断，总长度: {len(text)} 字符>"


def setup_http_logging(
    log_file: str = "http.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """配置 HTTP 日志记录
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别
        max_bytes: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件数量
    """
    from logging.handlers import RotatingFileHandler
    
    # 创建 HTTP 日志记录器
    http_logger.setLevel(log_level)
    
    # 创建文件 handler（带日志轮转）
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    
    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    
    # 添加 handler
    http_logger.addHandler(file_handler)
    
    # 防止日志传播到根 logger
    http_logger.propagate = False
    
    http_logger.info("HTTP 日志记录已启用")
    http_logger.info(f"日志文件: {log_file}")
    http_logger.info(f"最大文件大小: {max_bytes / 1024 / 1024:.1f} MB")
    http_logger.info(f"保留文件数: {backup_count}")
