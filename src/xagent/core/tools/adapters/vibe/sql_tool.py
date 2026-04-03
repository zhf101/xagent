"""SQL 工具适配层。

这一层把底层 `execute_sql_query` 接到 xagent 的工具体系里，并补上两类平台语义：
- 把 Task / DAG / step 的 runtime 信息注入到 SQL 审批策略上下文
- 把 SQL 工具结果落成 `DAGStepRun`，供恢复与审批页面使用
"""

import asyncio
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from textwrap import dedent, indent
from typing import TYPE_CHECKING, Any, Optional

from ....workspace import TaskWorkspace
from ...core.sql_tool import execute_sql_query, get_database_type
from ....policy.sql_policy_gateway import SQLPolicyGateway
from .base import ToolCategory
from .factory import ToolFactory, register_tool
from .function import FunctionTool

if TYPE_CHECKING:
    from .config import BaseToolConfig

logger = logging.getLogger(__name__)

_sql_policy_runtime_context: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "sql_policy_runtime_context", default=None
)


def set_sql_policy_runtime_context(context: dict[str, Any]) -> Token:
    return _sql_policy_runtime_context.set(context)


def reset_sql_policy_runtime_context(token: Token) -> None:
    _sql_policy_runtime_context.reset(token)


def get_sql_policy_runtime_context() -> Optional[dict[str, Any]]:
    return _sql_policy_runtime_context.get()


class SQLQueryFunctionTool(FunctionTool):
    """注册到工具市场的 SQL FunctionTool。"""

    category = ToolCategory.DATABASE


class SqlQueryTool:
    """平台内的 SQL 工具包装器。

    它对上暴露工具接口，对下调用核心 SQL 工具；
    同时负责在需要时接入审批策略与步骤执行事实落库。
    """

    def __init__(
        self,
        workspace: Optional[TaskWorkspace] = None,
        connection_map: Optional[dict[str, str]] = None,
        default_user_id: Optional[int] = None,
    ):
        """初始化 SQL 工具包装器。

        参数语义：
        - `workspace`：控制导出文件等工作区侧效果的落点
        - `connection_map`：连接名称到 URL 的映射，用于覆盖环境变量中的连接
        - `default_user_id`：当运行时上下文没有显式 user_id 时的兜底发起人
        """
        self._workspace = workspace
        self._connection_map = {
            key.upper(): value for key, value in (connection_map or {}).items()
        }
        self._default_user_id = default_user_id

    def _resolve_connection_url(self, connection_name: str) -> Optional[str]:
        return self._connection_map.get(connection_name.upper())

    async def execute_sql_query(
        self, connection_name: str, query: str, output_file: Optional[str] = None
    ) -> dict[str, Any]:
        """执行 SQL 工具入口。

        如果当前 runtime 没有注入审批上下文，则走普通 SQL 执行；
        如果有审批上下文，则进入带策略网关的受控执行链路。
        """
        runtime_context = get_sql_policy_runtime_context()
        connection_url = self._resolve_connection_url(connection_name)

        if runtime_context is None:
            return await asyncio.to_thread(
                execute_sql_query,
                connection_name,
                query,
                output_file,
                self._workspace,
                connection_url,
            )

        return await asyncio.to_thread(
            self._execute_sql_query_with_policy,
            connection_name,
            query,
            output_file,
            runtime_context,
            connection_url,
        )

    def get_database_type(self, connection_name: str) -> str:
        """返回连接对应数据库类型，供 LLM 选择正确 SQL 方言。"""
        return get_database_type(
            connection_name, self._resolve_connection_url(connection_name)
        )

    def get_tools(self) -> list:
        """构造并返回平台可注册的 SQL 工具列表。"""
        tools = [
            SQLQueryFunctionTool(
                self.get_database_type,
                name="get_database_type",
                description=indent(
                    dedent("""
                    Get the database type for a connection name.

                    This helps determine the SQL dialect to use when writing queries.
                    Different databases have different syntax and functions.

                    Args:
                        connection_name: Database connection name to check

                    Returns:
                        str: Database type (postgresql, mysql, sqlite, duckdb, etc.)
                """),
                    "" * 4,
                ),
                tags=["sql", "database", "metadata"],
            ),
            SQLQueryFunctionTool(
                self.execute_sql_query,
                name="execute_sql_query",
                description=indent(
                    dedent("""
                    Execute SQL queries on databases and return structured results.

                    TIP: Call get_database_type(connection_name) first to learn the SQL dialect
                    (postgresql, mysql, sqlite, duckdb have different syntax).

                        Args:
                            connection_name: (REQUIRED) The database connection name.
                            query: (REQUIRED) SQL statement to execute.
                                Use syntax matching the database type.
                            output_file: (OPTIONAL) Export results to file instead of returning them.
                                Supported: .csv, .parquet, .json, .jsonl, .ndjson (relative to workspace).
                                Use for large datasets to avoid response size limits.

                        Returns:
                            dict with keys:
                            - success: true if query worked
                            - rows: query results as list of dicts (SELECT only, empty when exported)
                            - row_count: number of rows returned or affected
                            - columns: column names in the result
                            - message: what happened (includes export info when applicable)
                """),
                    "" * 4,
                ),
                tags=[
                    "sql",
                    "database",
                    "query",
                    "postgresql",
                    "mysql",
                    "sqlite",
                    "duckdb",
                ],
            ),
        ]

        return tools

    def _execute_sql_query_with_policy(
        self,
        connection_name: str,
        query: str,
        output_file: Optional[str],
        runtime_context: dict[str, Any],
        connection_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """带审批策略的 SQL 执行分支。

        业务动作：
        - 从 web 层拿审批持久化依赖；
        - 拼装 policy_context；
        - 执行 SQL 或拿到阻断结果；
        - 把这次工具调用沉淀成 `DAGStepRun`。
        """
        try:
            from .....web.models.database import get_db
            from .....web.models.sql_approval import DAGStepRun
            from .....web.services.sql_approval_service import SQLApprovalService
        except Exception as exc:
            # 如果 web 层审批依赖不可用，平台宁可退化为直接执行，也不在工具层把能力整体打死。
            logger.warning(
                "SQL approval dependencies unavailable, falling back to direct SQL execution: %s",
                exc,
            )
            return execute_sql_query(
                connection_name,
                query,
                output_file,
                self._workspace,
                connection_url,
            )

        db_gen = get_db()
        db = next(db_gen)

        try:
            requested_by = runtime_context.get("requested_by") or self._default_user_id
            # 这里组装的是“平台级最小审批上下文”，保持和具体业务 prompt 解耦。
            policy_context = {
                "task_id": int(runtime_context["task_id"]),
                "plan_id": str(runtime_context["plan_id"]),
                "step_id": str(runtime_context["step_id"]),
                "environment": str(runtime_context.get("environment") or "prod"),
                "tool_name": "execute_sql_query",
                "tool_payload": {
                    "connection_name": connection_name,
                    "query": query,
                    "output_file": output_file,
                },
                "requested_by": int(requested_by or 0),
                "attempt_no": int(runtime_context.get("attempt_no") or 1),
                "dag_snapshot_version": int(
                    runtime_context.get("dag_snapshot_version") or 1
                ),
                "resume_token": str(runtime_context["resume_token"]),
            }

            result = execute_sql_query(
                connection_name,
                query,
                output_file,
                self._workspace,
                connection_url,
                policy_gateway=SQLPolicyGateway(
                    approval_service=SQLApprovalService(db),
                ),
                policy_context=policy_context,
            )

            status = self._resolve_step_run_status(result)
            policy_decision = result.get("policy_decision")
            approval_request_id = None
            if isinstance(policy_decision, dict):
                approval_request_id = policy_decision.get("approval_request_id")

            # 不论最终是成功、失败还是等待审批，都沉淀 step run，
            # 这样恢复页和审批摘要才能看到这次工具调用的真实现场。
            step_run = DAGStepRun(
                task_id=policy_context["task_id"],
                plan_id=policy_context["plan_id"],
                step_id=policy_context["step_id"],
                attempt_no=policy_context["attempt_no"],
                status=status,
                executor_type="dag_react_step",
                input_payload=runtime_context.get("step_input_payload"),
                resolved_context=runtime_context.get("resolved_context"),
                tool_name="execute_sql_query",
                tool_args={
                    "connection_name": connection_name,
                    "query": query,
                    "output_file": output_file,
                },
                tool_result=result if result.get("success") or result.get("blocked") else None,
                tool_error=None if result.get("success") else {"message": result.get("message")},
                policy_decision=policy_decision,
                approval_request_id=approval_request_id,
                started_at=datetime.now(timezone.utc),
                ended_at=datetime.now(timezone.utc),
            )
            db.add(step_run)
            db.commit()

            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _resolve_step_run_status(self, result: dict[str, Any]) -> str:
        """把 SQL 工具结果映射成步骤级状态。"""
        if result.get("blocked"):
            return "waiting_approval"
        if result.get("success"):
            return "completed"
        return "failed"


def get_sql_tool(info: Optional[dict[str, Any]] = None) -> list[FunctionTool]:
    """按当前上下文构造 SQL 工具。"""
    workspace: TaskWorkspace | None = None
    connection_map: dict[str, str] | None = None
    default_user_id: Optional[int] = None
    if info and "workspace" in info:
        workspace = (
            info["workspace"] if isinstance(info["workspace"], TaskWorkspace) else None
        )
    if info and "connection_map" in info and isinstance(info["connection_map"], dict):
        connection_map = {
            str(key): str(value)
            for key, value in info["connection_map"].items()
            if isinstance(key, str) and isinstance(value, str)
        }
    if info and "user_id" in info:
        default_user_id = (
            int(info["user_id"]) if info["user_id"] is not None else None
        )

    tool_instance = SqlQueryTool(
        workspace=workspace,
        connection_map=connection_map,
        default_user_id=default_user_id,
    )
    return tool_instance.get_tools()


@register_tool
async def create_sql_tools(config: "BaseToolConfig") -> list:
    """按工具配置创建 SQL 工具集合。

    这是框架自动发现入口，不包含业务逻辑。
    """
    workspace = ToolFactory._create_workspace(config.get_workspace_config())
    connection_map = config.get_sql_connections()
    tool_instance = SqlQueryTool(
        workspace,
        connection_map=connection_map,
        default_user_id=config.get_user_id(),
    )
    return tool_instance.get_tools()
