import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..auth_dependencies import get_current_user
from ..models.database import get_db, get_session_local
from ..models.task import Task, TaskStatus, TraceEvent
from ..models.user import User
from ..dynamic_memory_store import get_memory_store
from ..services.llm_utils import resolve_llms_from_names
from ...core.agent.context import AgentContext
from ...core.agent.pattern.data_make_react import DataMakeReActPattern
from ...core.agent.trace import Tracer
from ...core.datamake.ledger.sql_models import DataMakeFlowDraft
from ...core.datamake.ledger.persistent_repository import PersistentLedgerRepository
from ...core.datamake.resources.catalog import ResourceCatalog
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

    # 构建基础上下文
    context = AgentContext(task_id=str(task_id), session_id=f"session_{user.id}")
    
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
            task=user_input,
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
        user_input="", # 任务输入在挂钩里已包含在上下文中，这里可以传空或原标题
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
        task_status=str(task.status),
        flow_draft=flow_draft,
        execution_trace=execution_trace,
        recent_errors=recent_errors,
    )
