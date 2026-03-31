"""数据库操作日志记录

记录所有 SQLAlchemy 数据库操作到独立的 sql.log 文件。
"""

import logging
import time
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# 创建专门的 SQL 日志记录器
sql_logger = logging.getLogger("xagent.sql")


def setup_sql_logging(
    log_file: str = "sql.log",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    log_query_params: bool = True,
) -> None:
    """配置 SQL 日志记录
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别
        max_bytes: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件数量
        log_query_params: 是否记录查询参数
    """
    from logging.handlers import RotatingFileHandler
    
    # 创建 SQL 日志记录器
    sql_logger.setLevel(log_level)
    
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
    sql_logger.addHandler(file_handler)
    
    # 防止日志传播到根 logger
    sql_logger.propagate = False
    
    sql_logger.info("SQL 日志记录已启用")
    sql_logger.info(f"日志文件: {log_file}")
    sql_logger.info(f"记录查询参数: {log_query_params}")


class SQLQueryLogger:
    """SQL 查询日志记录器
    
    使用 SQLAlchemy 事件系统记录所有数据库操作。
    """
    
    def __init__(self, log_params: bool = True, log_results: bool = False):
        """初始化 SQL 查询日志记录器
        
        Args:
            log_params: 是否记录查询参数
            log_results: 是否记录查询结果（可能很大，慎用）
        """
        self.log_params = log_params
        self.log_results = log_results
        self._query_counter = 0
        self._query_times = {}
    
    def register_events(self, engine: Engine) -> None:
        """注册 SQLAlchemy 事件监听器
        
        Args:
            engine: SQLAlchemy Engine 实例
        """
        # 查询执行前
        event.listen(engine, "before_cursor_execute", self._before_cursor_execute)
        
        # 查询执行后
        event.listen(engine, "after_cursor_execute", self._after_cursor_execute)
        
        # 连接事件
        event.listen(engine, "connect", self._on_connect)
        event.listen(engine, "close", self._on_close)
        
        # 事务事件
        event.listen(engine, "begin", self._on_begin)
        event.listen(engine, "commit", self._on_commit)
        event.listen(engine, "rollback", self._on_rollback)
        
        sql_logger.info("SQL 事件监听器已注册")
    
    def _before_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """查询执行前的回调"""
        self._query_counter += 1
        query_id = self._query_counter
        
        # 记录开始时间
        conn.info.setdefault("query_start_time", {})[query_id] = time.time()
        
        sql_logger.info("=" * 100)
        sql_logger.info(f"[SQL 查询 #{query_id}] 开始")
        sql_logger.info("-" * 100)
        
        # 记录 SQL 语句
        sql_logger.info(f"[SQL 语句]")
        sql_logger.info(self._format_sql(statement))
        
        # 记录参数
        if self.log_params and parameters:
            sql_logger.info(f"[查询参数]")
            if executemany:
                sql_logger.info(f"  批量执行: {len(parameters)} 条")
                # 只显示前 3 条参数
                for i, params in enumerate(parameters[:3]):
                    sql_logger.info(f"  [{i+1}] {self._sanitize_params(params)}")
                if len(parameters) > 3:
                    sql_logger.info(f"  ... 还有 {len(parameters) - 3} 条")
            else:
                sql_logger.info(f"  {self._sanitize_params(parameters)}")
        
        # 保存 query_id 到 context
        context._query_id = query_id
    
    def _after_cursor_execute(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        """查询执行后的回调"""
        query_id = getattr(context, "_query_id", None)
        if query_id is None:
            return
        
        # 计算执行时间
        start_time = conn.info.get("query_start_time", {}).get(query_id)
        if start_time:
            execution_time = time.time() - start_time
            del conn.info["query_start_time"][query_id]
        else:
            execution_time = 0
        
        sql_logger.info("-" * 100)
        sql_logger.info(f"[SQL 查询 #{query_id}] 完成")
        sql_logger.info(f"[执行时间] {execution_time:.4f} 秒")
        
        # 记录影响的行数
        if cursor.rowcount >= 0:
            sql_logger.info(f"[影响行数] {cursor.rowcount}")
        
        # 记录结果（慎用，可能很大）
        if self.log_results and cursor.description:
            try:
                # 只记录前几行
                rows = cursor.fetchmany(5)
                if rows:
                    sql_logger.info(f"[查询结果] (前 5 行)")
                    for i, row in enumerate(rows):
                        sql_logger.info(f"  [{i+1}] {row}")
            except Exception as e:
                sql_logger.debug(f"无法获取查询结果: {e}")
        
        sql_logger.info("=" * 100)
        sql_logger.info("")  # 空行分隔
    
    def _on_connect(self, dbapi_conn: Any, connection_record: Any) -> None:
        """数据库连接建立时的回调"""
        sql_logger.debug(f"[数据库连接] 已建立")
    
    def _on_close(self, dbapi_conn: Any, connection_record: Any) -> None:
        """数据库连接关闭时的回调"""
        sql_logger.debug(f"[数据库连接] 已关闭")
    
    def _on_begin(self, conn: Any) -> None:
        """事务开始时的回调"""
        sql_logger.info("[事务] 开始")
    
    def _on_commit(self, conn: Any) -> None:
        """事务提交时的回调"""
        sql_logger.info("[事务] 提交")
    
    def _on_rollback(self, conn: Any) -> None:
        """事务回滚时的回调"""
        sql_logger.warning("[事务] 回滚")
    
    def _format_sql(self, statement: str) -> str:
        """格式化 SQL 语句"""
        # 简单的格式化，添加缩进
        statement = statement.strip()
        
        # 关键字换行
        keywords = ["SELECT", "FROM", "WHERE", "JOIN", "LEFT JOIN", "RIGHT JOIN", 
                   "INNER JOIN", "ORDER BY", "GROUP BY", "HAVING", "LIMIT", 
                   "INSERT INTO", "UPDATE", "DELETE FROM", "VALUES"]
        
        for keyword in keywords:
            statement = statement.replace(f" {keyword} ", f"\n  {keyword} ")
        
        return statement
    
    def _sanitize_params(self, params: Any) -> str:
        """过滤敏感参数"""
        if isinstance(params, dict):
            sanitized = {}
            sensitive_keys = ["password", "token", "secret", "api_key"]
            
            for key, value in params.items():
                key_lower = str(key).lower()
                if any(sensitive in key_lower for sensitive in sensitive_keys):
                    sanitized[key] = "***REDACTED***"
                else:
                    sanitized[key] = value
            
            return str(sanitized)
        
        elif isinstance(params, (list, tuple)):
            # 对于位置参数，无法判断是否敏感，直接返回
            return str(params)
        
        else:
            return str(params)


# 全局 SQL 查询日志记录器实例
_sql_query_logger: Optional[SQLQueryLogger] = None


def enable_sql_logging(
    engine: Engine,
    log_params: bool = True,
    log_results: bool = False,
) -> None:
    """启用 SQL 日志记录
    
    Args:
        engine: SQLAlchemy Engine 实例
        log_params: 是否记录查询参数
        log_results: 是否记录查询结果
    """
    global _sql_query_logger
    
    if _sql_query_logger is None:
        _sql_query_logger = SQLQueryLogger(
            log_params=log_params,
            log_results=log_results,
        )
        _sql_query_logger.register_events(engine)
        sql_logger.info("SQL 查询日志记录已启用")
    else:
        sql_logger.warning("SQL 查询日志记录已经启用，跳过重复注册")


def get_sql_logger() -> Optional[SQLQueryLogger]:
    """获取全局 SQL 查询日志记录器"""
    return _sql_query_logger
