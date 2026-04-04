## LLM日志功能概况

  1. 核心模块
   - 文件位置：src/xagent/core/model/chat/logging_callback.py
   - 日志名称：xagent.llm

  2. 启用方式
  通过环境变量控制：

   ### 启用LLM独立日志
   ENABLE_LLM_LOGGING="true"

   ### 日志文件路径（默认：llm_requests.log）
   LLM_LOG_FILE="llm_requests.log"

   ### 可选：启用底层HTTP日志（httpx, httpcore, openai, langchain）
   ENABLE_LLM_HTTP_LOGGING="true"

   ### 日志文件大小限制（默认：10MB）
   LLM_LOG_MAX_BYTES="10485760"

   ### 备份文件数量（默认：5个）
   LLM_LOG_BACKUP_COUNT="5"

  3. 日志内容
  记录以下信息：
   - 请求信息：
     - 模型名称、API基础URL
     - 消息列表（摘要，前20条）
     - 工具列表（仅工具名）
     - 调用类型、响应格式等

   - 响应信息：
     - 执行时间（毫秒）
     - 内容预览（前800字符）
     - 工具调用详情
     - Token使用情况（prompt/completion/total）

   - 错误信息：
     - 错误类型
     - 错误消息（前1200字符）
     - 执行时间

  4. 使用位置
   - OpenAI 适配器：chat/basic/openai.py - 使用 log_llm_request_start/end/error
   - LangChain 集成：chat/langchain.py - 使用 enable_llm_request_logging
   - 应用启动：web/app.py - 在应用启动时调用 setup_llm_logging_from_env()

  5. 安全特性
   - 敏感信息脱敏：使用 redact_sensitive_text() 函数处理敏感内容
   - 内容截断：避免日志过大，限制文本预览长度
   - 日志轮转：使用 RotatingFileHandler 自动轮转日志文件

  6. 当前配置
  在 example.env 中，LLM日志功能是默认关闭的（注释状态）：
   # ENABLE_LLM_LOGGING="true"
   # LLM_LOG_FILE="llm_requests.log"


## SQL 日志功能概况

  1. 核心模块
   - 文件位置：src/xagent/core/database/sql_logging.py
   - 日志名称：xagent.sql

  2. 启用方式
  通过环境变量控制：

   ### 启用SQL独立日志
   ENABLE_SQL_LOGGING="true"

   ### 日志文件路径（默认：sql.log）
   SQL_LOG_FILE="sql.log"

   ### 是否记录查询参数（默认：true）
   SQL_LOG_QUERY_PARAMS="true"

   ### 是否记录查询结果（默认：false，避免日志过大）
   SQL_LOG_RESULTS="false"

   ### 日志文件大小限制（默认：10MB）
   SQL_LOG_MAX_BYTES="10485760"

   ### 备份文件数量（默认：5个）
   SQL_LOG_BACKUP_COUNT="5"

  3. 日志内容

  应用数据库 SQL（通过 SQLAlchemy 事件监听）
   - 查询开始：
     - 查询ID、SQL语句（前4000字符）
     - 参数（脱敏处理）
     - 是否批量执行

   - 查询结束：
     - 执行时间（毫秒）
     - 影响行数
     - 列信息（可选）

   - 事务事件：
     - 事务开始
     - 事务提交
     - 事务回滚（警告级别）

  外部数据源 SQL（通过 SQL 工具主动打点）
  记录以下事件：
   - query_requested - 查询请求
   - query_blocked - 查询被策略拦截
   - query_approved - 查询通过审批
   - query_started - 查询开始执行
   - query_completed - 查询完成
   - query_failed - 查询失败
   - export_started - 导出开始
   - export_completed - 导出完成
   - export_failed - 导出失败
   - policy_decision - 策略决策

  4. 使用位置
   - 应用启动：web/app.py - 初始化时调用 enable_sql_logging()
   - SQL 工具：core/tools/core/sql_tool.py - 在10个关键位置调用 log_sql_tool_event()

  5. 安全特性
   - 敏感信息脱敏：
     - SQL 参数脱敏：redact_sensitive_text()
     - 数据库URL脱敏：redact_url_credentials_for_logging()

   - 内容截断：
     - SQL 语句限制4000字符
     - 参数列表限制前20个

   - 日志轮转：
     - 使用 RotatingFileHandler 自动轮转
     - 默认每个文件10MB，保留5个备份

  6. 日志示例

  应用数据库 SQL：
   2026-04-04 10:30:45 INFO     xagent.sql - [DB SQL start] {"query_id": 1, "statement": "SELECT * FROM
   users WHERE id = :id", "parameters": {"id": "***"}}
   2026-04-04 10:30:45 INFO     xagent.sql - [DB SQL end] {"query_id": 1, "elapsed_ms": 12.5, "rowcount": 1}

  外部数据源 SQL：
   2026-04-04 10:30:50 INFO     xagent.sql - [SQL tool query_requested] {"connection_name": "analytics",
   "query": "SELECT COUNT(*) FROM orders", "has_policy_gateway": true}
   2026-04-04 10:30:51 INFO     xagent.sql - [SQL tool query_approved] {"connection_name": "analytics",
   "decision": "allow_direct"}
   2026-04-04 10:30:52 INFO     xagent.sql - [SQL tool query_completed] {"connection_name": "analytics",
   "row_count": 1523, "elapsed_ms": 145.2}

  7. 当前配置
  在 example.env 中，SQL日志功能是默认关闭的（注释状态）：
   # ENABLE_SQL_LOGGING="true"
   # SQL_LOG_FILE="sql.log"
   # SQL_LOG_QUERY_PARAMS="true"
   # SQL_LOG_RESULTS="false"

