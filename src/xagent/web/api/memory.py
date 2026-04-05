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
from ..models.database import get_db
from ..models.memory_job import MemoryJob
from ..models.user import User
from ..memory_utils import serialize_memory_bundle, serialize_memory_note
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
            # Backward compatibility: use static memory store
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
        else:
            return self.get_memory_store()

    def _setup_routes(self) -> None:
        def serialize_job(job: MemoryJob) -> dict[str, Any]:
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
            if getattr(user, "is_admin", False):
                return query
            return query.filter(MemoryJob.source_user_id == int(user.id))

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
                query = apply_job_access_filter(db.query(MemoryJob), user)
                filters_used: dict[str, Any] = {}

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
                raise HTTPException(
                    status_code=500, detail=f"Failed to list memory jobs: {str(e)}"
                )

        @self.router.get("/jobs/{job_id}", response_model=MemoryJobResponse)
        async def get_memory_job(
            job_id: int,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> MemoryJobResponse:
            try:
                job = (
                    apply_job_access_filter(
                        db.query(MemoryJob).filter(MemoryJob.id == job_id), user
                    )
                    .first()
                )
                if job is None:
                    raise HTTPException(status_code=404, detail="Memory job not found")
                return MemoryJobResponse(**serialize_job(job))
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory job: {str(e)}"
                )

        @self.router.post("/jobs/{job_id}/retry")
        async def retry_memory_job(
            job_id: int,
            user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> dict[str, Any]:
            try:
                job = (
                    apply_job_access_filter(
                        db.query(MemoryJob).filter(MemoryJob.id == job_id), user
                    )
                    .first()
                )
                if job is None:
                    raise HTTPException(status_code=404, detail="Memory job not found")

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
                db.rollback()
                raise HTTPException(
                    status_code=500, detail=f"Failed to retry memory job: {str(e)}"
                )

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
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    # Build filters
                    filters: dict[str, Any] = {}
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

                    # Get memories
                    if search:
                        # Use search functionality if search query is provided
                        search_results = self.memory_store.search(
                            query=search,
                            k=1000,
                            filters=filters if filters else None,
                            similarity_threshold=similarity_threshold,
                        )
                        memories = search_results
                    else:
                        # Use regular list_all if no search query
                        memories = self.memory_store.list_all(filters)

                    # Apply pagination
                    total_count = len(memories)
                    memories = memories[offset : offset + limit]

                    # Convert to dict format for response
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
                    bundle = retriever.retrieve(memory_query)
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

        @self.router.delete("/{memory_id}")
        async def delete_memory(
            memory_id: str, user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            try:
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    response = self.memory_store.delete(memory_id)
                    if response.success:
                        return {
                            "success": True,
                            "message": "Memory deleted successfully",
                        }
                    else:
                        raise HTTPException(
                            status_code=404, detail=response.error or "Memory not found"
                        )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to delete memory: {str(e)}"
                )

        @self.router.put("/{memory_id}")
        async def update_memory(
            memory_id: str,
            update_request: MemoryUpdateRequest,
            user: User = Depends(get_current_user),
        ) -> dict[str, Any]:
            try:
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    # Get existing memory
                    get_response = self.memory_store.get(memory_id)
                    if not get_response.success:
                        raise HTTPException(status_code=404, detail="Memory not found")

                    existing_memory = get_response.content
                    if not isinstance(existing_memory, MemoryNote):
                        raise HTTPException(
                            status_code=500, detail="Invalid memory data"
                        )

                    # Update fields that are provided
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

                    # Rebuild from the existing note so provenance/governance fields survive
                    updated_memory_data = existing_memory.model_dump()
                    updated_memory_data.update(updates)
                    updated_memory = MemoryNote(**updated_memory_data)

                    # Update in store
                    response = self.memory_store.update(updated_memory)
                    if response.success:
                        return {
                            "success": True,
                            "message": "Memory updated successfully",
                        }
                    else:
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

        @self.router.get("/stats", response_model=MemoryStatsResponse)
        async def get_memory_stats(
            user: User = Depends(get_current_user),
        ) -> MemoryStatsResponse:
            try:
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    stats = self.memory_store.get_stats()
                    return MemoryStatsResponse(**stats)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory stats: {str(e)}"
                )

        @self.router.post("")
        async def create_memory(
            memory_request: dict[str, Any], user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            # Validate required fields
            if "content" not in memory_request:
                raise HTTPException(status_code=422, detail="Content field is required")
            try:
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    # Create new memory note
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

                    response = self.memory_store.add(memory_note)
                    if response.success:
                        return {
                            "success": True,
                            "memory_id": response.memory_id,
                            "message": "Memory created successfully",
                        }
                    else:
                        raise HTTPException(
                            status_code=500,
                            detail=response.error or "Failed to create memory",
                        )

            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to create memory: {str(e)}"
                )

        @self.router.get("/{memory_id}")
        async def get_memory(
            memory_id: str, user: User = Depends(get_current_user)
        ) -> dict[str, Any]:
            try:
                # Set user context for memory operations
                with UserContext(int(user.id)):
                    response = self.memory_store.get(memory_id)
                    if response.success and response.content:
                        memory = response.content
                        if isinstance(memory, MemoryNote):
                            return serialize_memory_note(memory)
                        else:
                            return {"content": memory}
                    else:
                        raise HTTPException(
                            status_code=404, detail=response.error or "Memory not found"
                        )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get memory: {str(e)}"
                )

        @self.router.get("/store-info")
        async def get_store_info(user: User = Depends(get_current_user)) -> dict:
            """Get current memory store information for debugging"""
            try:
                manager = get_memory_store_manager()
                return manager.get_store_info()
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to get store info: {str(e)}"
                )

    def get_router(self) -> APIRouter:
        return self.router
