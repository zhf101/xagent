from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.user import User
from ..services.task_prompt_recommendation_service import get_task_prompt_recommendations

recommendation_router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


class RecommendedExample(BaseModel):
    title: str
    description: str
    prompt: str


class ModePromptRecommendations(BaseModel):
    recommended_examples: list[RecommendedExample]
    confidence: float
    fallback_needed: bool
    last_updated_at: Optional[str] = None
    evidence_summary: Optional[dict[str, Any]] = None


class TaskPromptRecommendationsResponse(BaseModel):
    data_generation: ModePromptRecommendations
    data_consultation: ModePromptRecommendations
    general: ModePromptRecommendations


@recommendation_router.get("/task-prompts", response_model=TaskPromptRecommendationsResponse)
async def get_recommended_task_prompts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskPromptRecommendationsResponse:
    try:
        payload = get_task_prompt_recommendations(db, int(user.id))
        return TaskPromptRecommendationsResponse(**payload)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load task prompt recommendations: {exc}"
        )
