import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..auth_dependencies import get_current_user
from ..models.database import get_db, get_session_local
from ..models.task import Task, TaskStatus
from ..models.user import User
from ..dynamic_memory_store import get_memory_store
from ..services.llm_utils import resolve_llms_from_names
from ...core.agent.context import AgentContext
from ...core.agent.pattern.data_make_react import DataMakeReActPattern
from ...core.agent.trace import Tracer
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
