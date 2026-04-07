"""记忆管理 Web API。

这个文件是前端/调试端和记忆系统交互的统一入口。
本次迁移后，这里不再只是简单 CRUD，还多了两类能力：
1. 结构化记忆调试检索：方便看 session summary / durable / experience 实际取到了什么。
2. memory job 管理：方便查看后台提取/合并/过期任务的状态与重试情况。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case
from sqlalchemy.orm import Session

from xagent.core.memory.base import MemoryStore
from xagent.core.memory.core import MemoryNote
from xagent.core.memory.job_repository import MemoryJobRepository
from xagent.core.memory.job_types import MemoryJobStatus
from xagent.core.memory.retriever import MemoryQuery, MemoryRetriever

from ..auth_dependencies import get_current_user
from ..dynamic_memory_store import get_memory_store_manager
from ..memory_utils import serialize_memory_bundle, serialize_memory_note
from ..models.database import get_db
from ..models.memory_job import MemoryJob
from ..models.user import User
from ..user_isolated_memory import UserContext


class MemoryListRequest(BaseModel):
    category: Optional[str] = Field(None, description="Filter by memory category")
    tags: Optional[list[str]] = Field(
        None, description="Filter by tags (all must match)"
    )
    keywords: Optional[list[str]] = Field(
        None, description="Filter by keywords (all must match)"
    )
    date_from: Optional[datetime] = Field(
        None, description="Filter memories from this date"
    )
    date_to: Optional[datetime] = Field(
        None, description="Filter memories to this date"
    )
    limit: Optional[int] = Field(
        100, description="Maximum number of memories to return"
    )
    offset: Optional[int] = Field(0, description="Offset for pagination")


class MemoryUpdateRequest(BaseModel):
    content: Optional[str] = Field(None, description="Updated memory content")
    keywords: Optional[list[str]] = Field(None, description="Updated memory keywords")
    tags: Optional[list[str]] = Field(None, description="Updated memory tags")
    category: Optional[str] = Field(None, description="Updated memory category")
    memory_type: Optional[str] = Field(None, description="Updated memory type")
    memory_subtype: Optional[str] = Field(None, description="Updated memory subtype")
    scope: Optional[str] = Field(None, description="Updated memory scope")
    project_id: Optional[str] = Field(None, description="Updated project ID")
    workspace_id: Optional[str] = Field(None, description="Updated workspace ID")
    importance: Optional[int] = Field(None, description="Updated importance")
    confidence: Optional[float] = Field(None, description="Updated confidence")
    status: Optional[str] = Field(None, description="Updated status")
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Updated memory metadata"
    )


class MemoryListResponse(BaseModel):
    memories: list[dict[str, Any]]
    total_count: int
    filters_used: dict[str, Any]


class MemoryDebugResponse(BaseModel):
    query: str
    filters_used: dict[str, Any]
    bundle: dict[str, Any]


class MemoryJobResponse(BaseModel):
    id: int
    job_type: str
    status: str
    priority: int
    payload_json: dict[str, Any]
    dedupe_key: Optional[str] = None
    source_task_id: Optional[str] = None
    source_session_id: Optional[str] = None
    source_user_id: Optional[int] = None
    source_project_id: Optional[str] = None
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_until: Optional[datetime] = None
    locked_by: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class MemoryJobListResponse(BaseModel):
    jobs: list[MemoryJobResponse]
    total_count: int
    filters_used: dict[str, Any]


class MemoryStatsResponse(BaseModel):
    total_count: int
    category_counts: dict[str, int]
    tag_counts: dict[str, int]
    memory_store_type: str
    error: Optional[str] = None


class MemoryManagementRouter:
    def __init__(
        self, memory_store_provider: Optional[Callable[[], MemoryStore]] = None
    ) -> None:
        """
        Initialize memory management router.

        Args:
            memory_store_provider: Optional function that returns a memory store.
                                  If not provided, uses the static memory_store.
        """
        if memory_store_provider is not None:
            self.get_memory_store = memory_store_provider
            self._static_memory_store = None
        else:
            # 这里保留“静态 store”兼容位，是为了让测试或离线场景仍然能注入固定 store。
            self._static_memory_store = None

        self.router = APIRouter(prefix="/api/memory", tags=["memory"])
        self._setup_routes()

    @property
    def memory_store(self) -> MemoryStore:
        """Get the current memory store (supports dynamic switching)"""
        if (
            hasattr(self, "_static_memory_store")
            and self._static_memory_store is not None
        ):
            return self._static_memory_store
        return self.get_memory_store()

    def _setup_routes(self) -> None:
        def serialize_job(job: MemoryJob) -> dict[str, Any]:
            # ORM 模型里有很多 SQLAlchemy 字段对象，先统一压成普通 dict 再返回给前端。
            return {
                "id": int(job.id),
                "job_type": str(job.job_type),
                "status": str(job.status),
                "priority": int(job.priority),
                "payload_json": dict(job.payload_json or {}),
                "dedupe_key": job.dedupe_key,
                "source_task_id": job.source_task_id,
                "source_session_id": job.source_session_id,
                "source_user_id": job.source_user_id,
                "source_project_id": job.source_project_id,
                "attempt_count": int(job.attempt_count or 0),
                "max_attempts": int(job.max_attempts or 0),
                "available_at": job.available_at,
                "lease_until": job.lease_until,
                "locked_by": job.locked_by,
                "last_error": job.last_error,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            }

        def apply_job_access_filter(query: Any, user: User) -> Any:
            # 非管理员只能看自己触发的记忆任务，避免跨用户查看后台治理记录。
            if getattr(user, "is_admin", False):
                return query
            return query.filter(MemoryJob.source_user_id == int(user.id))

        # 后台治理任务列表：
        # 给前端/开发者查看当前有哪些记忆提取、合并、过期任务，以及它们的状态。
        @self.router.get("/jobs", response_model=MemoryJobListResponse)
        async def list_memory_jobs(
            job_type: Optional[str] = Query(None, description="Filter by job type"),
            status: Optional[str] = Query(None, description="Filter by job status"),
            source_task_id: Optional[str] = Query(
                None, description="Filter by source task ID"
            ),
            source_session_id: Optional[str] = Query(
                None, description="Filter by source session ID"
            ),
            source_project_id: Optional[str] = Query(
                None, description="Filter by source project ID"
            ),
            limit: int = Query(100, ge=1, le=500, description="Maximum jobs to return"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> MemoryJobListResponse:
            try:
                # 第一步：先按当前用户身份裁剪可见范围。
                # 非管理员后面无论带什么筛选条件，都只能在“自己的 job 子集”里查。
                query = apply_job_access_filter(db.query(MemoryJob), user)
                filters_used: dict[str, Any] = {}

                # 第二步：把前端传来的可选筛选条件逐项落到 SQL 查询里，
                # 同时把实际生效的条件记录到 filters_used，方便前端回显和调试。
                if job_type:
                    query = query.filter(MemoryJob.job_type == job_type)
                    filters_used["job_type"] = job_type
                if status:
                    query = query.filter(MemoryJob.status == status)
                    filters_used["status"] = status
                if source_task_id:
                    query = query.filter(MemoryJob.source_task_id == source_task_id)
                    filters_used["source_task_id"] = source_task_id
                if source_session_id:
                    query = query.filter(
                        MemoryJob.source_session_id == source_session_id
                    )
                    filters_used["source_session_id"] = source_session_id
                if source_project_id:
                    query = query.filter(
                        MemoryJob.source_project_id == source_project_id
                    )
                    filters_used["source_project_id"] = source_project_id

                # 这里刻意把失败/死亡/取消任务排在前面，
                # 这样前端排查问题时，第一眼就能看到异常 job。
                failed_first_order = case(
                    (
                        MemoryJob.status.in_(
                            [
                                MemoryJobStatus.FAILED.value,
                                MemoryJobStatus.DEAD.value,
                                MemoryJobStatus.CANCELLED.value,
                            ]
                        ),
                        0,
                    ),
                    else_=1,
                )
                total_count = query.count()
                # 第三步：先 count 总数，再做排序+分页，
                # 这样前端分页组件可以知道总共有多少条记录。
                jobs = (
                    query.order_by(
                        failed_first_order.asc(),
                        MemoryJob.created_at.desc(),
                        MemoryJob.id.desc(),
                    )
                    .offset(offset)
                    .limit(limit)
                    .all()
                )
                return MemoryJobListResponse(
                    jobs=[MemoryJobResponse(**serialize_job(job)) for job in jobs],
                    total_count=total_count,
                    filters_used=filters_used,
                )
            except Exception as e:
                # 这里统一包成 HTTPException，前端能收到稳定的错误结构。
                raise HTTPException(
                    status_code=500, detail=f"Failed to list memory jobs: {str(e)}"
                )

        # 查看单个后台记忆任务详情。
        @self.router.get("/jobs/{job_id}", response_model=MemoryJobResponse)
        async def get_memory_job(
            job_id: int,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> MemoryJobResponse:
            try:
                # 先做用户权限过滤，再按 id 查询，
                # 避免通过直接猜 job_id 越权查看别人的后台任务。
                job = (
                    apply_job_access_filter(
                        db.query(MemoryJob).filter(MemoryJob.id == job_id), user
                    )
                    .first()
                )
                if job is None:
                    raise HTTPException(status_code=404, detail="Memory job not found")
                # ORM 对象要先序列化，再交给响应模型做最终校验。
                return MemoryJobResponse(**serialize_job(job))
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory job: {str(e)}"
                )

        # 对失败/死亡/取消的任务做人工重试。
        @self.router.post("/jobs/{job_id}/retry")
        async def retry_memory_job(
            job_id: int,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> dict[str, Any]:
            try:
                # 第一步：确认这个 job 存在且当前用户有权看到它。
                job = (
                    apply_job_access_filter(
                        db.query(MemoryJob).filter(MemoryJob.id == job_id), user
                    )
                    .first()
                )
                if job is None:
                    raise HTTPException(status_code=404, detail="Memory job not found")

                # 第二步：只允许对“已经结束且状态异常”的任务做人手重试。
                # 正在运行或待执行的任务如果重置，会破坏队列一致性。
                if job.status not in {
                    MemoryJobStatus.FAILED.value,
                    MemoryJobStatus.DEAD.value,
                    MemoryJobStatus.CANCELLED.value,
                }:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Only failed, dead, or cancelled memory jobs can be retried"
                        ),
                    )

                # 第三步：真正的重试逻辑下沉到 repository，
                # 路由层只负责事务提交与返回组织。
                retried_job = MemoryJobRepository(db).reset_job_for_retry(int(job.id))
                db.commit()
                if retried_job is None:
                    raise HTTPException(status_code=404, detail="Memory job not found")
                return {
                    "success": True,
                    "message": "Memory job retried successfully",
                    "job": serialize_job(retried_job),
                }
            except HTTPException:
                raise
            except Exception as e:
                # 这里要显式 rollback，避免 SQLAlchemy 会话残留脏事务。
                db.rollback()
                raise HTTPException(
                    status_code=500, detail=f"Failed to retry memory job: {str(e)}"
                )

        # 传统的记忆列表查询接口，主要给管理页做 CRUD 使用。
        @self.router.get("/list", response_model=MemoryListResponse)
        async def list_memories(
            category: Optional[str] = Query(None, description="Filter by category"),
            memory_type: Optional[str] = Query(
                None, description="Filter by structured memory type"
            ),
            memory_subtype: Optional[str] = Query(
                None, description="Filter by structured memory subtype"
            ),
            scope: Optional[str] = Query(None, description="Filter by scope"),
            project_id: Optional[str] = Query(None, description="Filter by project ID"),
            workspace_id: Optional[str] = Query(
                None, description="Filter by workspace ID"
            ),
            status: Optional[str] = Query(None, description="Filter by memory status"),
            tags: Optional[str] = Query(
                None, description="Comma-separated tags to filter"
            ),
            keywords: Optional[str] = Query(
                None, description="Comma-separated keywords to filter"
            ),
            date_from: Optional[datetime] = Query(
                None, description="Filter from this date"
            ),
            date_to: Optional[datetime] = Query(
                None, description="Filter to this date"
            ),
            search: Optional[str] = Query(
                None, description="Search query to filter memories by content"
            ),
            similarity_threshold: Optional[float] = Query(
                None, description="Similarity threshold for vector search (0.1-2.0)"
            ),
            limit: int = Query(
                100, ge=1, le=1000, description="Maximum results to return"
            ),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            user: User = Depends(get_current_user),
        ) -> MemoryListResponse:
            try:
                with UserContext(int(user.id)):
                    # 这里使用 UserContext 包裹，是因为底层 memory store 支持用户隔离。
                    # 只要进入这个上下文，后续查询就会自动落在当前用户自己的记忆空间。
                    filters: dict[str, Any] = {}
                    # 把查询参数逐项映射成底层 store 能理解的过滤条件。
                    # 这一步不直接查库，只是整理过滤字典。
                    if category:
                        filters["category"] = category
                    if memory_type:
                        filters["memory_type"] = memory_type
                    if memory_subtype:
                        filters["memory_subtype"] = memory_subtype
                    if scope:
                        filters["scope"] = scope
                    if project_id:
                        filters["project_id"] = project_id
                    if workspace_id:
                        filters["workspace_id"] = workspace_id
                    if status:
                        filters["status"] = status
                    if tags:
                        filters["tags"] = [
                            tag.strip() for tag in tags.split(",") if tag.strip()
                        ]
                    if keywords:
                        filters["keywords"] = [
                            kw.strip() for kw in keywords.split(",") if kw.strip()
                        ]
                    if date_from:
                        filters["date_from"] = date_from
                    if date_to:
                        filters["date_to"] = date_to

                    # 如果带 search，说明用户希望走“内容检索”模式；
                    # 否则就走 list_all，做纯过滤浏览。
                    if search:
                        memories = self.memory_store.search(
                            query=search,
                            k=1000,
                            filters=filters if filters else None,
                            similarity_threshold=similarity_threshold,
                        )
                    else:
                        memories = self.memory_store.list_all(filters)

                    # 底层 store 先把结果全量返回，这里再做 API 层分页切片。
                    total_count = len(memories)
                    memories = memories[offset : offset + limit]
                    # 最终统一序列化成适合前端展示的普通 dict。
                    memory_dicts = [serialize_memory_note(memory) for memory in memories]

                    return MemoryListResponse(
                        memories=memory_dicts,
                        total_count=total_count,
                        filters_used=filters,
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to list memories: {str(e)}"
                )

        # 结构化调试检索接口：
        # 用来观察新版 retriever 实际返回了哪些 session/durable/experience 记忆。
        @self.router.get("/debug-search", response_model=MemoryDebugResponse)
        async def debug_search_memories(
            query: str = Query(..., description="Search query for layered retrieval"),
            session_id: Optional[str] = Query(None, description="Optional session ID"),
            include_durable: bool = Query(
                True, description="Include durable memories in bundle"
            ),
            include_session_summary: bool = Query(
                True, description="Include session summary in bundle"
            ),
            include_knowledge: bool = Query(
                False, description="Include knowledge memories in bundle"
            ),
            durable_limit: int = Query(2, ge=0, le=20),
            experience_limit: int = Query(3, ge=0, le=20),
            session_summary_limit: int = Query(1, ge=0, le=10),
            knowledge_limit: int = Query(3, ge=0, le=20),
            similarity_threshold: Optional[float] = Query(
                None, description="Similarity threshold for layered retrieval"
            ),
            user: User = Depends(get_current_user),
        ) -> MemoryDebugResponse:
            try:
                with UserContext(int(user.id)):
                    # debug-search 的目标不是做通用 CRUD，
                    # 而是显式演示新版结构化检索器会查出哪些层次的记忆。
                    retriever = MemoryRetriever(self.memory_store)
                    memory_query = MemoryQuery(
                        query=query,
                        session_id=session_id,
                        include_durable=include_durable,
                        include_session_summary=include_session_summary,
                        include_knowledge=include_knowledge,
                        durable_limit=durable_limit,
                        experience_limit=experience_limit,
                        session_summary_limit=session_summary_limit,
                        knowledge_limit=knowledge_limit,
                        similarity_threshold=similarity_threshold,
                    )
                    # 真正的 layered retrieval 在这里发生。
                    bundle = retriever.retrieve(memory_query)
                    # 把本次查询配置原样回传，方便前端或开发者复盘“为什么查到了这些结果”。
                    filters_used = {
                        "session_id": session_id,
                        "include_durable": include_durable,
                        "include_session_summary": include_session_summary,
                        "include_knowledge": include_knowledge,
                        "durable_limit": durable_limit,
                        "experience_limit": experience_limit,
                        "session_summary_limit": session_summary_limit,
                        "knowledge_limit": knowledge_limit,
                        "similarity_threshold": similarity_threshold,
                    }
                    return MemoryDebugResponse(
                        query=query,
                        filters_used=filters_used,
                        bundle=serialize_memory_bundle(bundle),
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to debug search memories: {str(e)}",
                )

        # 删除单条记忆。
        @self.router.delete("/{memory_id}")
        async def delete_memory(
            memory_id: str, user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            try:
                with UserContext(int(user.id)):
                    # 删除动作依然要在用户隔离上下文里执行，
                    # 防止误删到别的用户的记忆。
                    response = self.memory_store.delete(memory_id)
                    if response.success:
                        return {
                            "success": True,
                            "message": "Memory deleted successfully",
                        }
                    raise HTTPException(
                        status_code=404, detail=response.error or "Memory not found"
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to delete memory: {str(e)}"
                )

        # 更新单条记忆，支持编辑结构化字段。
        @self.router.put("/{memory_id}")
        async def update_memory(
            memory_id: str,
            update_request: MemoryUpdateRequest,
            user: User = Depends(get_current_user),
        ) -> dict[str, Any]:
            try:
                with UserContext(int(user.id)):
                    # 先查旧记录，是为了保留那些这次没有更新的字段。
                    get_response = self.memory_store.get(memory_id)
                    if not get_response.success:
                        raise HTTPException(status_code=404, detail="Memory not found")

                    existing_memory = get_response.content
                    if not isinstance(existing_memory, MemoryNote):
                        raise HTTPException(
                            status_code=500, detail="Invalid memory data"
                        )

                    # 只把请求里显式传入的字段放进 updates，
                    # 这样接口行为就是“部分更新”，而不是必须整条重传。
                    updates: dict[str, Any] = {}
                    if update_request.content is not None:
                        updates["content"] = update_request.content
                    if update_request.keywords is not None:
                        updates["keywords"] = update_request.keywords
                    if update_request.tags is not None:
                        updates["tags"] = update_request.tags
                    if update_request.category is not None:
                        updates["category"] = update_request.category
                    if update_request.memory_type is not None:
                        updates["memory_type"] = update_request.memory_type
                    if update_request.memory_subtype is not None:
                        updates["memory_subtype"] = update_request.memory_subtype
                    if update_request.scope is not None:
                        updates["scope"] = update_request.scope
                    if update_request.project_id is not None:
                        updates["project_id"] = update_request.project_id
                    if update_request.workspace_id is not None:
                        updates["workspace_id"] = update_request.workspace_id
                    if update_request.importance is not None:
                        updates["importance"] = update_request.importance
                    if update_request.confidence is not None:
                        updates["confidence"] = update_request.confidence
                    if update_request.status is not None:
                        updates["status"] = update_request.status
                    if update_request.metadata is not None:
                        updates["metadata"] = update_request.metadata

                    # 先把旧对象 dump 成 dict，再叠加局部更新字段，
                    # 最后重新构造 MemoryNote，让 Pydantic 再跑一遍字段归一化逻辑。
                    updated_memory_data = existing_memory.model_dump()
                    updated_memory_data.update(updates)
                    updated_memory = MemoryNote(**updated_memory_data)

                    # 真正写回底层 store。
                    response = self.memory_store.update(updated_memory)
                    if response.success:
                        return {
                            "success": True,
                            "message": "Memory updated successfully",
                        }
                    raise HTTPException(
                        status_code=500,
                        detail=response.error or "Failed to update memory",
                    )

            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to update memory: {str(e)}"
                )

        # 统计接口，给前端显示当前记忆库总体规模。
        @self.router.get("/stats", response_model=MemoryStatsResponse)
        async def get_memory_stats(
            user: User = Depends(get_current_user),
        ) -> MemoryStatsResponse:
            try:
                with UserContext(int(user.id)):
                    # 统计信息完全交给底层 store 计算，
                    # 路由层只负责把结果包装成响应模型。
                    stats = self.memory_store.get_stats()
                    return MemoryStatsResponse(**stats)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory stats: {str(e)}"
                )

        # 创建记忆接口，允许从管理端手工补充记忆。
        @self.router.post("")
        async def create_memory(
            memory_request: dict[str, Any], user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            # content 是 MemoryNote 的最核心字段，没有它就不是一条有效记忆。
            if "content" not in memory_request:
                raise HTTPException(status_code=422, detail="Content field is required")
            try:
                with UserContext(int(user.id)):
                    # 这里把外部传入的原始 dict 显式映射到 MemoryNote，
                    # 避免把未知字段直接透传到底层对象里。
                    memory_note = MemoryNote(
                        content=memory_request.get("content", ""),
                        keywords=memory_request.get("keywords", []),
                        tags=memory_request.get("tags", []),
                        category=memory_request.get("category", "general"),
                        memory_type=memory_request.get("memory_type"),
                        memory_subtype=memory_request.get("memory_subtype"),
                        scope=memory_request.get("scope", "user"),
                        project_id=memory_request.get("project_id"),
                        workspace_id=memory_request.get("workspace_id"),
                        importance=memory_request.get("importance", 3),
                        confidence=memory_request.get("confidence", 0.5),
                        status=memory_request.get("status", "active"),
                        metadata=memory_request.get("metadata", {}),
                    )

                    # 创建动作最终还是交给 memory_store，这样 in-memory 和 LanceDB 共用同一套路由。
                    response = self.memory_store.add(memory_note)
                    if response.success:
                        return {
                            "success": True,
                            "memory_id": response.memory_id,
                            "message": "Memory created successfully",
                        }
                    raise HTTPException(
                        status_code=500,
                        detail=response.error or "Failed to create memory",
                    )

            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to create memory: {str(e)}"
                )

        # 获取单条记忆详情。
        @self.router.get("/{memory_id}")
        async def get_memory(
            memory_id: str, user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            try:
                with UserContext(int(user.id)):
                    # 先从当前用户隔离空间读取目标记忆。
                    response = self.memory_store.get(memory_id)
                    if response.success and response.content:
                        memory = response.content
                        # 如果底层返回的是标准 MemoryNote，就走统一序列化；
                        # 否则退化成最小可展示结构。
                        if isinstance(memory, MemoryNote):
                            return serialize_memory_note(memory)
                        return {"content": memory}
                    raise HTTPException(
                        status_code=404, detail=response.error or "Memory not found"
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory: {str(e)}"
                )

        # 返回当前底层 memory store 的实现信息，便于调试是 LanceDB 还是 in-memory。
        @self.router.get("/store-info")
        async def get_store_info(user: User = Depends(get_current_user)) -> dict:
            """Get current memory store information for debugging"""
            try:
                # 这里不直接访问 self.memory_store，
                # 因为我们要的是 manager 级别的调试信息，而不只是 store 实例本身。
                manager = get_memory_store_manager()
                return manager.get_store_info()
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get store info: {str(e)}"
                )

    def get_router(self) -> APIRouter:
        return self.router
