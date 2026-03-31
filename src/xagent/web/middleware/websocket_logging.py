"""WebSocket 连接和消息日志记录

记录所有 WebSocket 连接、消息和事件到独立的 websocket.log 文件。
"""

import json
import logging
import time
from typing import Any, Callable, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

# 创建专门的 WebSocket 日志记录器
ws_logger = logging.getLogger("xagent.websocket")


def setup_websocket_logging(
    log_file: str = "websocket.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """配置 WebSocket 日志记录
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别
        max_bytes: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件数量
    """
    from logging.handlers import RotatingFileHandler
    
    # 创建 WebSocket 日志记录器
    ws_logger.setLevel(log_level)
    
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
    ws_logger.addHandler(file_handler)
    
    # 防止日志传播到根 logger
    ws_logger.propagate = False
    
    ws_logger.info("WebSocket 日志记录已启用")
    ws_logger.info(f"日志文件: {log_file}")


class WebSocketLogger:
    """WebSocket 日志记录器
    
    记录 WebSocket 连接、消息发送/接收、错误等事件。
    """
    
    def __init__(
        self,
        log_messages: bool = True,
        log_ping_pong: bool = False,
        max_message_length: int = 1000,
    ):
        """初始化 WebSocket 日志记录器
        
        Args:
            log_messages: 是否记录消息内容
            log_ping_pong: 是否记录 ping/pong 消息
            max_message_length: 消息最大记录长度（字符）
        """
        self.log_messages = log_messages
        self.log_ping_pong = log_ping_pong
        self.max_message_length = max_message_length
        self._connection_counter = 0
        self._message_counter = {}
    
    def log_connection(
        self,
        websocket: WebSocket,
        client_info: Optional[dict] = None,
    ) -> int:
        """记录 WebSocket 连接建立
        
        Args:
            websocket: WebSocket 实例
            client_info: 客户端信息（如用户 ID、会话 ID 等）
            
        Returns:
            连接 ID
        """
        self._connection_counter += 1
        conn_id = self._connection_counter
        
        ws_logger.info("=" * 100)
        ws_logger.info(f"[WebSocket 连接 #{conn_id}] 已建立")
        ws_logger.info("-" * 100)
        
        # 记录客户端信息
        if websocket.client:
            ws_logger.info(f"[客户端] {websocket.client.host}:{websocket.client.port}")
        
        # 记录路径
        ws_logger.info(f"[路径] {websocket.url.path}")
        
        # 记录 Query 参数
        if websocket.query_params:
            ws_logger.info(f"[Query 参数] {dict(websocket.query_params)}")
        
        # 记录 Headers
        ws_logger.info(f"[Headers]")
        for key, value in websocket.headers.items():
            # 过滤敏感信息
            if key.lower() in ["authorization", "cookie"]:
                value = "***REDACTED***"
            ws_logger.info(f"  {key}: {value}")
        
        # 记录额外的客户端信息
        if client_info:
            ws_logger.info(f"[客户端信息]")
            for key, value in client_info.items():
                ws_logger.info(f"  {key}: {value}")
        
        ws_logger.info("=" * 100)
        ws_logger.info("")
        
        # 初始化消息计数器
        self._message_counter[conn_id] = 0
        
        return conn_id
    
    def log_disconnect(
        self,
        conn_id: int,
        reason: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> None:
        """记录 WebSocket 连接断开
        
        Args:
            conn_id: 连接 ID
            reason: 断开原因
            duration: 连接持续时间（秒）
        """
        ws_logger.info("=" * 100)
        ws_logger.info(f"[WebSocket 连接 #{conn_id}] 已断开")
        ws_logger.info("-" * 100)
        
        if reason:
            ws_logger.info(f"[断开原因] {reason}")
        
        if duration is not None:
            ws_logger.info(f"[连接时长] {duration:.2f} 秒")
        
        # 记录消息统计
        message_count = self._message_counter.get(conn_id, 0)
        ws_logger.info(f"[消息总数] {message_count}")
        
        ws_logger.info("=" * 100)
        ws_logger.info("")
        
        # 清理计数器
        if conn_id in self._message_counter:
            del self._message_counter[conn_id]
    
    def log_receive(
        self,
        conn_id: int,
        message: Any,
        message_type: str = "text",
    ) -> None:
        """记录接收到的消息
        
        Args:
            conn_id: 连接 ID
            message: 消息内容
            message_type: 消息类型（text, bytes, json）
        """
        if not self.log_messages:
            return
        
        # 跳过 ping/pong
        if not self.log_ping_pong and message_type in ["ping", "pong"]:
            return
        
        self._message_counter[conn_id] = self._message_counter.get(conn_id, 0) + 1
        msg_id = self._message_counter[conn_id]
        
        ws_logger.info("-" * 100)
        ws_logger.info(f"[WebSocket #{conn_id}] 接收消息 #{msg_id}")
        ws_logger.info(f"[消息类型] {message_type}")
        
        # 记录消息内容
        if message_type == "json":
            try:
                # 过滤敏感字段
                sanitized = self._sanitize_json(message)
                message_str = json.dumps(sanitized, ensure_ascii=False, indent=2)
            except Exception:
                message_str = str(message)
        elif message_type == "bytes":
            message_str = f"<二进制数据，长度: {len(message)} 字节>"
        else:
            message_str = str(message)
        
        # 截断过长的消息
        if len(message_str) > self.max_message_length:
            message_str = (
                message_str[: self.max_message_length]
                + f"\n... <截断，总长度: {len(message_str)} 字符>"
            )
        
        ws_logger.info(f"[消息内容]")
        ws_logger.info(message_str)
        ws_logger.info("-" * 100)
        ws_logger.info("")
    
    def log_send(
        self,
        conn_id: int,
        message: Any,
        message_type: str = "text",
    ) -> None:
        """记录发送的消息
        
        Args:
            conn_id: 连接 ID
            message: 消息内容
            message_type: 消息类型（text, bytes, json）
        """
        if not self.log_messages:
            return
        
        # 跳过 ping/pong
        if not self.log_ping_pong and message_type in ["ping", "pong"]:
            return
        
        self._message_counter[conn_id] = self._message_counter.get(conn_id, 0) + 1
        msg_id = self._message_counter[conn_id]
        
        ws_logger.info("-" * 100)
        ws_logger.info(f"[WebSocket #{conn_id}] 发送消息 #{msg_id}")
        ws_logger.info(f"[消息类型] {message_type}")
        
        # 记录消息内容
        if message_type == "json":
            try:
                # 过滤敏感字段
                sanitized = self._sanitize_json(message)
                message_str = json.dumps(sanitized, ensure_ascii=False, indent=2)
            except Exception:
                message_str = str(message)
        elif message_type == "bytes":
            message_str = f"<二进制数据，长度: {len(message)} 字节>"
        else:
            message_str = str(message)
        
        # 截断过长的消息
        if len(message_str) > self.max_message_length:
            message_str = (
                message_str[: self.max_message_length]
                + f"\n... <截断，总长度: {len(message_str)} 字符>"
            )
        
        ws_logger.info(f"[消息内容]")
        ws_logger.info(message_str)
        ws_logger.info("-" * 100)
        ws_logger.info("")
    
    def log_error(
        self,
        conn_id: int,
        error: Exception,
        context: Optional[str] = None,
    ) -> None:
        """记录 WebSocket 错误
        
        Args:
            conn_id: 连接 ID
            error: 异常对象
            context: 错误上下文
        """
        ws_logger.error("-" * 100)
        ws_logger.error(f"[WebSocket #{conn_id}] 错误")
        
        if context:
            ws_logger.error(f"[上下文] {context}")
        
        ws_logger.error(f"[错误类型] {type(error).__name__}")
        ws_logger.error(f"[错误信息] {str(error)}")
        ws_logger.error("-" * 100)
        ws_logger.error("")
    
    def _sanitize_json(self, data: Any) -> Any:
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
                key_lower = str(key).lower()
                if any(sensitive in key_lower for sensitive in sensitive_keys):
                    sanitized[key] = "***REDACTED***"
                else:
                    sanitized[key] = self._sanitize_json(value)
            
            return sanitized
        
        elif isinstance(data, list):
            return [self._sanitize_json(item) for item in data]
        
        else:
            return data


# 全局 WebSocket 日志记录器实例
_ws_logger: Optional[WebSocketLogger] = None


def get_websocket_logger() -> WebSocketLogger:
    """获取全局 WebSocket 日志记录器
    
    Returns:
        WebSocketLogger 实例
    """
    global _ws_logger
    
    if _ws_logger is None:
        _ws_logger = WebSocketLogger()
    
    return _ws_logger


class LoggedWebSocket:
    """带日志记录的 WebSocket 包装器
    
    自动记录所有 WebSocket 操作。
    
    使用示例:
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            
            # 包装 WebSocket
            logged_ws = LoggedWebSocket(websocket, client_info={"user_id": 123})
            
            # 使用包装后的 WebSocket
            message = await logged_ws.receive_text()
            await logged_ws.send_json({"response": "ok"})
    """
    
    def __init__(
        self,
        websocket: WebSocket,
        client_info: Optional[dict] = None,
        logger: Optional[WebSocketLogger] = None,
    ):
        """初始化带日志的 WebSocket
        
        Args:
            websocket: 原始 WebSocket 实例
            client_info: 客户端信息
            logger: WebSocket 日志记录器（可选）
        """
        self.websocket = websocket
        self.logger = logger or get_websocket_logger()
        self.conn_id = self.logger.log_connection(websocket, client_info)
        self.connect_time = time.time()
    
    async def receive_text(self) -> str:
        """接收文本消息"""
        message = await self.websocket.receive_text()
        self.logger.log_receive(self.conn_id, message, "text")
        return message
    
    async def receive_json(self) -> Any:
        """接收 JSON 消息"""
        message = await self.websocket.receive_json()
        self.logger.log_receive(self.conn_id, message, "json")
        return message
    
    async def receive_bytes(self) -> bytes:
        """接收二进制消息"""
        message = await self.websocket.receive_bytes()
        self.logger.log_receive(self.conn_id, message, "bytes")
        return message
    
    async def send_text(self, data: str) -> None:
        """发送文本消息"""
        self.logger.log_send(self.conn_id, data, "text")
        await self.websocket.send_text(data)
    
    async def send_json(self, data: Any) -> None:
        """发送 JSON 消息"""
        self.logger.log_send(self.conn_id, data, "json")
        await self.websocket.send_json(data)
    
    async def send_bytes(self, data: bytes) -> None:
        """发送二进制消息"""
        self.logger.log_send(self.conn_id, data, "bytes")
        await self.websocket.send_bytes(data)
    
    async def close(self, code: int = 1000, reason: Optional[str] = None) -> None:
        """关闭连接"""
        duration = time.time() - self.connect_time
        self.logger.log_disconnect(self.conn_id, reason, duration)
        await self.websocket.close(code, reason)
    
    def __getattr__(self, name: str) -> Any:
        """代理其他属性到原始 WebSocket"""
        return getattr(self.websocket, name)
