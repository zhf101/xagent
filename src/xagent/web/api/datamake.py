import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..auth_dependencies import get_current_user
from ..models.database import get_db, get_session_local
from ..models.task import Task, TaskStatus, TraceEvent
from ..models.text2sql import Text2SQLDatabase
from ..models.user import User
from ..dynamic_memory_store import get_memory_store
from ..services.llm_utils import resolve_llms_from_names
from ...core.agent.context import AgentContext
from ...core.agent.pattern.data_make_react import DataMakeReActPattern
from ...core.agent.trace import Tracer
from ...core.datamake.application.interaction import UiResponseMapper
from ...core.datamake.application.supervision import SupervisionBridge
from ...core.datamake.contracts.interaction import ApprovalTicket, InteractionTicket
from ...core.datamake.ledger.sql_models import DataMakeFlowDraft
from ...core.datamake.ledger.persistent_repository import PersistentLedgerRepository
from ...core.datamake.resources.catalog import ResourceCatalog
from ...core.datamake.resources.sql_resource_definition import (
    SqlResourceMetadata,
    build_sql_resource_action_payload,
)
from .trace_handlers import DatabaseTraceHandler
from .ws_trace_handlers import WebSocketTraceHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/datamake", tags=["datamake"])

class DataMakeChatRequest(BaseModel):
    task_id: Optional[int] = None
    input: str
    llm_ids: Optional[list[str]] = None

class DataMakeInteractRequest(BaseModel):
    task_id: int
    ticket_id: Optional[str] = None
    approval_id: Optional[str] = None
    reply: Any
    field: str


class DataMakeContextResponse(BaseModel):
    """
    datamake 右侧上下文面板使用的真实数据视图。

    这个接口只负责把已经持久化的事实重新组织给 UI：
    - `flow_draft`：当前工作草稿视图
    - `execution_trace`：真正进入 Runtime / Resource 后写回账本的 observation
    - `recent_errors`：主脑阶段最近的错误，帮助区分“没执行到底层”与“底层执行失败”
    """

    task_id: int
    task_status: str
    flow_draft: dict[str, Any] | None = None
    execution_trace: list[dict[str, Any]]
    recent_errors: list[dict[str, Any]]
    pending_resume: "DataMakePendingResumeResponse | None" = None


class DataMakePendingResumeResponse(BaseModel):
    """
    datamake 详情页恢复等待态所需的最小协议。

    它的职责不是重新驱动主脑，而是把账本里已经存在的 pending ticket
    转成前端可直接恢复渲染的字段集合，避免详情页刷新后丢失 Human in Loop 上下文。
    """

    status: str
    question: str
    field: str
    ticket_id: str | None = None
    approval_id: str | None = None
    chat_response: dict[str, Any] | None = None


DataMakeContextResponse.model_rebuild()


def _safe_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _build_execution_trace_item(record: dict[str, Any]) -> dict[str, Any] | None:
    """
    从账本 observation 里提取 UI 真正关心的执行摘要。

    这里刻意只暴露“用户能理解且调试有用”的那部分字段：
    - 当前轮次与状态
    - 资源/动作标识
    - facts 中的 transport / protocol / business / http_status
    - data 中保留的原始返回
    """

    if record.get("record_type") != "observation":
        return None

    observation = record.get("observation")
    if not isinstance(observation, dict):
        return None

    observation_type = str(observation.get("observation_type") or "")
    if observation_type not in {"execution", "failure", "blocker"}:
        return None

    payload = observation.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    facts = payload.get("facts")
    facts = facts if isinstance(facts, dict) else {}
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}

    return {
        "round_id": record.get("round_id"),
        "record_id": record.get("id"),
        "created_at": record.get("created_at"),
        "observation_type": observation_type,
        "status": observation.get("status"),
        "summary": (observation.get("result") or {}).get("summary")
        if isinstance(observation.get("result"), dict)
        else None,
        "error": observation.get("error"),
        "action": observation.get("action"),
        "action_kind": observation.get("action_kind"),
        "resource_key": payload.get("resource_key"),
        "operation_key": payload.get("operation_key"),
        "mode": payload.get("mode"),
        "evidence": observation.get("evidence") if isinstance(observation.get("evidence"), list) else [],
        "facts": {
            "transport_status": facts.get("transport_status"),
            "protocol_status": facts.get("protocol_status"),
            "business_status": facts.get("business_status"),
            "http_status": facts.get("http_status"),
            "normalizer": facts.get("normalizer"),
        },
        "data": data,
    }


def _build_recent_error_item(event: TraceEvent) -> dict[str, Any]:
    data = event.data if isinstance(event.data, dict) else {}
    error_type = str(data.get("error_type") or "")
    error_message = str(data.get("error_message") or "")
    stage = "general"
    title = error_type or "UnknownError"
    hint = "请查看错误详情。"
    transient = False

    if "Round" in error_message and "决策失败" in error_message:
        stage = "llm_decision"
    elif "Round" in error_message and "分发失败" in error_message:
        stage = "dispatch"

    if "RemoteProtocolError" in error_type or "Server disconnected without sending a response" in error_message:
        title = "模型网关连接被中断"
        hint = "这通常是上游模型网关瞬时断连。系统会自动重试；若持续出现，请检查模型代理稳定性。"
        transient = True
        stage = "llm_transport"
    elif error_type == "ValidationError" and "action_kind" in error_message:
        title = "模型返回了非法决策"
        hint = "模型输出了 decision_mode=action 但缺少 action_kind/action。当前版本会在解析阶段拦截并重试。"
        stage = "llm_contract"
    elif "未知 action_kind" in error_message:
        title = "非法决策进入了动作分发"
        hint = "这是决策契约未拦住的坏输出，说明分发前拿到了不完整的 action 决策。"
        stage = "dispatch_contract"

    return {
        "event_id": str(event.event_id),
        "step_id": event.step_id,
        "timestamp": _safe_timestamp(event.timestamp),
        "error_type": error_type or None,
        "error_message": error_message or None,
        "round_id": data.get("round_id"),
        "attempt": data.get("attempt"),
        "retryable": data.get("retryable"),
        "stage": stage,
        "title": title,
        "hint": hint,
        "transient": transient,
    }


def _build_pending_resume_response(
    *,
    interaction_ticket: InteractionTicket | None,
    approval_ticket: ApprovalTicket | None,
) -> DataMakePendingResumeResponse | None:
    """
    从持久化 pending ticket 复原详情页需要的等待态视图。

    这里刻意保持和 `pattern.run()` 的等待态返回同构：
    - `status/question/field`
    - `ticket_id/approval_id`
    - `chat_response`

    这样前端 hook 只需要维护一套等待态渲染逻辑，不会因为“实时返回”和“刷新恢复”
    变成两套协议。
    """

    ui_mapper = UiResponseMapper()
    supervision_bridge = SupervisionBridge()

    if interaction_ticket is not None:
        return DataMakePendingResumeResponse(
            status="waiting_user",
            question="\n".join(interaction_ticket.questions),
            field=interaction_ticket.response_field,
            ticket_id=interaction_ticket.ticket_id,
            chat_response=ui_mapper.to_chat_payload(interaction_ticket),
        )

    if approval_ticket is not None:
        return DataMakePendingResumeResponse(
            status="waiting_human",
            question=supervision_bridge.build_waiting_question(approval_ticket),
            field=approval_ticket.response_field,
            approval_id=approval_ticket.approval_id,
            chat_response=ui_mapper.to_approval_chat_payload(approval_ticket),
        )

    return None


def _resolve_datamake_task_prompt(task: Task, user_input: str) -> str:
    """
    统一解析本轮 datamake 运行真正要沿用的任务描述。

    这里刻意把“当前输入”和“原始任务描述”分开处理：
    - 新建任务 / 显式继续提新需求时，优先使用本次 `user_input`
    - `/interact` 恢复执行时，HTTP 层通常只携带补充字段，不会再带原始需求；
      这时必须回退到 `task.description`，否则 recall / 决策会丢失主任务目标
    """

    normalized_input = str(user_input or "").strip()
    if normalized_input:
        return normalized_input

    original_description = str(task.description or "").strip()
    if original_description:
        return original_description

    raise HTTPException(status_code=400, detail="造数任务缺少原始任务描述，无法恢复执行")


def _serialize_task_status(status: Any) -> str:
    """
    把 SQLAlchemy 任务状态统一收敛成前端约定的字面值。

    FastAPI 直接对 `Enum` 做 `str()` 会得到 `TaskStatus.RUNNING` 这类调试串，
    但 datamake 前端轮询与展示都依赖 `"running" / "completed"` 这类稳定字面值。
    """

    if isinstance(status, TaskStatus):
        return status.value
    if isinstance(status, str):
        return status
    return "unknown"


def _coerce_optional_int(value: Any) -> int | None:
    """
    把可能来自 JSON 的数字输入安全收敛成 `int | None`。
    """

    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _build_task_config_resource_action(
    task: Task,
) -> dict[str, Any] | None:
    """
    从任务自身的 `agent_config` 提取一条显式绑定的数据源动作。

    这条路径优先服务“任务创建时已经明确绑定单一数据库”的场景，
    让 datamake 不必完全依赖用户当前数据库列表推断资源边界。
    """

    config = task.agent_config if isinstance(task.agent_config, dict) else {}
    if not config:
        return None

    datasource_id = config.get("datasource_id") or config.get("database_id")
    text2sql_database_id = config.get("text2sql_database_id") or datasource_id
    database_url = config.get("database_url") or config.get("db_url")
    connection_name = config.get("connection_name")

    if not any([datasource_id, text2sql_database_id, database_url, connection_name]):
        return None

    database_name = str(config.get("database_name") or "任务绑定数据源").strip() or "任务绑定数据源"
    database_type = str(config.get("database_type") or config.get("db_type") or "").strip() or None
    read_only = bool(config.get("read_only", True))

    return build_sql_resource_action_payload(
        resource_key=f"task_{task.id}_bound_database",
        operation_key="execute_sql",
        description=(
            f"面向任务绑定数据源“{database_name}”执行受控 SQL。"
            "主脑必须先确认筛选范围、时间口径与目标表，再决定是否执行。"
        ),
        sql_metadata=SqlResourceMetadata(
            db_type=database_type,
            connection_name=str(connection_name).strip() if isinstance(connection_name, str) and connection_name.strip() else None,
            datasource_id=_coerce_optional_int(datasource_id),
            text2sql_database_id=_coerce_optional_int(text2sql_database_id),
            db_url=str(database_url).strip() if isinstance(database_url, str) and database_url.strip() else None,
            read_only=read_only,
        ),
        supports_probe=True,
        requires_approval=not read_only,
    )


def _build_user_text2sql_resource_actions(
    db: Session,
    user: User,
) -> list[dict[str, Any]]:
    """
    为当前用户已配置的数据源注入 datamake 可执行资源动作。

    设计取舍：
    - 这里不直接把完整数据库 URL 暴露给主脑，只注入 datasource 标识与只读约束
    - Runtime 需要真实连接信息时，再通过 `SqlDatasourceResolver` 回查宿主表
    - 这样既能让 `available_resources` 非空，又不会把敏感连接串塞进 LLM 上下文
    """

    databases = (
        db.query(Text2SQLDatabase)
        .filter(Text2SQLDatabase.user_id == user.id)
        .order_by(Text2SQLDatabase.id.asc())
        .all()
    )

    resource_actions: list[dict[str, Any]] = []
    for database in databases:
        database_name = str(database.name or f"数据库{database.id}").strip() or f"数据库{database.id}"
        database_type = getattr(database.type, "value", None) or str(database.type)
        resource_actions.append(
            build_sql_resource_action_payload(
                resource_key=f"text2sql_database_{database.id}",
                operation_key="execute_sql",
                description=(
                    f"面向数据源“{database_name}”执行受控 SQL。"
                    "优先用于探测、校验、查询与造数前置分析。"
                ),
                sql_metadata=SqlResourceMetadata(
                    db_type=str(database_type).strip() if database_type else None,
                    datasource_id=int(database.id),
                    text2sql_database_id=int(database.id),
                    read_only=bool(database.read_only),
                ),
                supports_probe=True,
                requires_approval=not bool(database.read_only),
            )
        )

    return resource_actions


def _build_datamake_resource_actions(
    task: Task,
    db: Session,
    user: User,
) -> list[dict[str, Any]]:
    """
    汇总本次 datamake 运行可见的受控资源动作。

    顺序约束：
    1. 任务显式绑定的数据源优先，避免用户期望单库执行时被其他数据库噪音稀释
    2. 再补充当前用户名下可见的数据源，保证 datamake 至少拿到真实可执行 catalog
    """

    resource_actions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()

    explicit_action = _build_task_config_resource_action(task)
    if explicit_action is not None:
        pair = (
            str(explicit_action.get("resource_key") or ""),
            str(explicit_action.get("operation_key") or ""),
        )
        seen_pairs.add(pair)
        resource_actions.append(explicit_action)

    for action in _build_user_text2sql_resource_actions(db, user):
        pair = (
            str(action.get("resource_key") or ""),
            str(action.get("operation_key") or ""),
        )
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        resource_actions.append(action)

    return resource_actions

async def _run_datamake_pattern(
    task_id: int, 
    user_input: str, 
    db: Session, 
    user: User, 
    llm_ids: Optional[list[str]] = None,
    interaction_reply: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """核心运载逻辑，驱动 DataMakeReActPattern"""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_prompt = _resolve_datamake_task_prompt(task, user_input)

    # 构建基础上下文
    context = AgentContext(task_id=str(task_id), session_id=f"session_{user.id}")
    context.user_id = str(user.id)
    context.state["datamake_resource_actions"] = _build_datamake_resource_actions(
        task=task,
        db=db,
        user=user,
    )
    
    # 恢复挂起回复（如果是 interact 重入）
    if interaction_reply:
        context.state[interaction_reply["field"]] = interaction_reply["reply"]

    # 解析 LLM
    default_llm, _, _, compact_llm = resolve_llms_from_names(llm_ids or [], db, int(user.id))

    # 挂载 Tracer（包含 DB 与 WebSocket 实时追踪）
    tracer = Tracer()
    tracer.add_handler(DatabaseTraceHandler(task_id))
    tracer.add_handler(WebSocketTraceHandler(task_id))

    # 初始化真正的造数主脑
    pattern = DataMakeReActPattern(
        llm=default_llm,
        compact_llm=compact_llm,
        tracer=tracer,
        ledger_repository=PersistentLedgerRepository(session_factory=get_session_local()),
        resource_catalog=ResourceCatalog()
    )

    try:
        # 修改为运行态
        task.status = TaskStatus.RUNNING
        db.commit()

        result = await pattern.run(
            task=task_prompt,
            memory=get_memory_store(),
            tools=[],  # 暂不从外部接通用工具，而是基于 resource_catalog
            context=context
        )

        # 判断中断还是结束
        if result.get("status") in ("waiting_user", "waiting_human"):
            task.status = TaskStatus.PAUSED
        elif result.get("status") == "completed":
            task.status = TaskStatus.COMPLETED
        else:
            task.status = TaskStatus.FAILED
            
        db.commit()
        return result
    except Exception as e:
        import traceback
        error_msg = f"DataMake Pattern error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        task.status = TaskStatus.FAILED
        db.commit()
        # 将具体错误详情返回给前端以便调试
        raise HTTPException(status_code=500, detail=f"造数引擎执行异常: {str(e)}")


@router.post("/chat")
async def datamake_chat(
    request: DataMakeChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """发起或继续智能造数对话/任务"""
    task_id = request.task_id
    if not task_id:
        # 如果是新任务，先创建一个
        task = Task(
            user_id=user.id,
            title="造数任务",
            description=request.input,
            status=TaskStatus.PENDING,
            agent_type="datamake"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    
    # 实际运行（在生产环境可用 BackgroundTasks 改为异步，这里为了即时返回 waiting 票据采用同步 await）
    result = await _run_datamake_pattern(
        task_id=task_id,
        user_input=request.input,
        db=db,
        user=user,
        llm_ids=request.llm_ids
    )

    return {"task_id": task_id, "result": result}


@router.post("/interact")
async def datamake_interact(
    request: DataMakeInteractRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """提交用户补充信息或审批结果并恢复执行"""
    task = db.query(Task).filter(Task.id == request.task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    interaction_reply = {
        "field": request.field,
        "reply": request.reply,
        "ticket_id": request.ticket_id,
        "approval_id": request.approval_id
    }

    result = await _run_datamake_pattern(
        task_id=request.task_id,
        user_input="",
        db=db,
        user=user,
        interaction_reply=interaction_reply
    )

    return {"task_id": request.task_id, "result": result}


@router.get("/tasks/{task_id}/context", response_model=DataMakeContextResponse)
async def get_datamake_task_context(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    读取 datamake 任务右侧上下文面板需要的真实数据。

    设计边界：
    - 不重新推导业务结论，只回放已落库事实
    - `execution_trace` 只展示真正进入 Runtime / Resource 的 observation
    - 如果根本没执行到底层资源，UI 应该看到空执行轨迹 + 最近错误，而不是 mock 假数据
    """

    task = db.query(Task).filter(Task.id == task_id, Task.user_id == user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    draft_row = db.get(DataMakeFlowDraft, str(task_id))
    flow_draft = None
    if draft_row is not None and isinstance(draft_row.draft_json, dict):
        flow_draft = dict(draft_row.draft_json)

    ledger_repository = PersistentLedgerRepository(session_factory=get_session_local())
    records = await ledger_repository.list_records(str(task_id))
    pending_interaction = await ledger_repository.load_pending_interaction(str(task_id))
    pending_approval = await ledger_repository.load_pending_approval(str(task_id))
    execution_trace = [
        item
        for item in (
            _build_execution_trace_item(record)
            for record in records
        )
        if item is not None
    ]

    recent_errors = [
        _build_recent_error_item(event)
        for event in (
            db.query(TraceEvent)
            .filter(
                TraceEvent.task_id == task_id,
                TraceEvent.build_id.is_(None),
                TraceEvent.event_type == "trace_error",
            )
            .order_by(TraceEvent.timestamp.desc(), TraceEvent.id.desc())
            .limit(10)
            .all()
        )
    ]

    return DataMakeContextResponse(
        task_id=task_id,
        task_status=_serialize_task_status(task.status),
        flow_draft=flow_draft,
        execution_trace=execution_trace,
        recent_errors=recent_errors,
        pending_resume=_build_pending_resume_response(
            interaction_ticket=pending_interaction,
            approval_ticket=pending_approval,
        ),
    )
