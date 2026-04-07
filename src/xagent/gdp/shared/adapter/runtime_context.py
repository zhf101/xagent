"""为工具运行时补齐上下文的公共辅助函数。

这个模块解决的不是业务问题，而是“工具在执行时需要哪些宿主信息”的问题。

对于 HTTP / SQL 这类工具来说，真正执行时至少要知道：

- 当前数据库会话 `db`
- 当前用户是谁 `user_id / user_name`
- 当前任务是谁 `task_id`
- 当前任务有没有已经确认过的 SQL 目标
- 当前任务有没有注入特定 LLM

这些信息原始上都散落在 `WebToolConfig` 里，直接让每个工具自己去解析会造成：

1. 每个工具都重复写一遍相同的上下文提取逻辑
2. 不同工具对 `task_id`、`user_name` 的解析规则不一致
3. 新人很难判断“某个工具执行时到底拿到了哪些上下文”

所以这里专门提供一个统一入口，把配置对象归一化为 `WebToolRuntimeContext`。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from xagent.web.models.user import User
from xagent.gdp.shared.service.task_target_resolution_service import (
    TaskTargetResolutionService,
)

if TYPE_CHECKING:
    from xagent.web.tools.config import WebToolConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WebToolRuntimeContext:
    """工具真正执行时依赖的最小上下文。

    这里刻意只保留最常用的运行时字段，而不是把整个 `WebToolConfig`
    暴露给下游服务。这样做有两个好处：

    - 下游 service 更容易测试，因为依赖更少
    - 新人读代码时能快速理解“工具执行到底要用到哪些宿主能力”
    """

    db: Any
    user_id: int
    user_name: str | None = None
    task_id: int | None = None
    llm: Any | None = None


def coerce_task_id(raw_task_id: Any) -> int | None:
    """把形如 ``task-6``、``6``、`6` 的输入统一转成整数 task_id。

    历史上不同调用方对 task_id 的传法并不完全一致：

    - 有的直接传整数
    - 有的传字符串 `"6"`
    - 有的传业务前缀形式 `"task-6"`

    这里统一做一次兜底，避免每个工具都自己写一遍正则。
    """
    if raw_task_id is None:
        return None
    if isinstance(raw_task_id, int):
        return raw_task_id
    matched = re.search(r"(\d+)$", str(raw_task_id))
    if matched is None:
        return None
    return int(matched.group(1))


def resolve_owner_user_name(db: Any, user_id: int) -> str | None:
    """补查用户名，给日志、运行记录和审计字段使用。

    很多 service 只拿到了 `user_id`，但落运行记录时通常还希望带上用户名，
    这样排查问题时更直观。
    """
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        return None
    username = getattr(user, "username", None)
    return str(username) if username is not None else None


def load_task_confirmed_target(
    db: Any,
    *,
    task_id: int | None,
    user_id: int,
) -> dict[str, Any] | None:
    """读取任务范围内已经确认过的 SQL 目标。

    典型场景：

    - 用户先在任务里确认“本次要访问 CRM 生产库”
    - 后续 `query_vanna_sql_asset` / `execute_vanna_sql_asset`
      就应该默认沿用这个目标，而不是每次都重新猜
    """
    if task_id is None:
        return None
    try:
        return TaskTargetResolutionService(db).load_confirmed_target(
            task_id=int(task_id),
            owner_user_id=int(user_id),
        )
    except Exception as exc:
        logger.warning(
            "Failed to load task-confirmed target for task %s: %s",
            task_id,
            exc,
        )
        return None


def build_web_tool_runtime_context(
    config: "WebToolConfig",
) -> WebToolRuntimeContext | None:
    """把 WebToolConfig 变成工具可直接使用的标准上下文。

    返回 `None` 表示当前调用环境不具备运行这些 GDP 工具的条件，
    比如没有数据库会话或没有登录用户。
    """
    if not hasattr(config, "get_db") or not hasattr(config, "get_user_id"):
        return None

    db = config.get_db()
    user_id = config.get_user_id()
    if not user_id:
        return None

    return WebToolRuntimeContext(
        db=db,
        user_id=int(user_id),
        user_name=resolve_owner_user_name(db, int(user_id)),
        task_id=coerce_task_id(
            config.get_task_id() if hasattr(config, "get_task_id") else None
        ),
        llm=config.get_llm() if hasattr(config, "get_llm") else None,
    )

