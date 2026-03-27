from datetime import datetime
from typing import Any, List

from pydantic import BaseModel, field_validator


class UserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_active: bool | None = None
    auth_source: str | None = None
    display_name: str | None = None
    email: str | None = None
    created_at: str
    updated_at: str

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def format_datetime(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    users: List[UserResponse]
    total: int
    page: int
    size: int
    pages: int
