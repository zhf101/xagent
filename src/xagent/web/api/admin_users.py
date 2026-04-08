from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth_dependencies import get_current_user
from ..models.database import get_db
from ..models.task import Task
from ..models.user import User
from ..schemas.user import UserListResponse, UserResponse

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


@router.get("", response_model=UserListResponse)
async def get_users(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str = Query("", description="Search username"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserListResponse:
    """分页返回用户列表。

    这里只做后台管理所需的最小查询能力：
    - 用户名模糊搜索
    - 标准分页
    - 管理员权限校验
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Build query
    query = db.query(User)

    # Apply search filter
    if search:
        query = query.filter(User.username.like(f"%{search}%"))

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * size
    users = query.offset(offset).limit(size).all()

    return UserListResponse(
        users=[UserResponse.model_validate(user) for user in users],
        total=total,
        page=page,
        size=size,
        pages=(total + size - 1) // size,
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除用户。

    这个接口的关键点不是删 `users` 表本身，而是先清理显式不会自动级联的数据，
    避免数据库残留悬挂记录或外键冲突。
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Cannot delete yourself
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete related data in correct order to respect foreign key constraints
    from ..models.mcp import UserMCPServer
    from ..models.system_registry import UserSystemRole
    from ..models.text2sql import Text2SQLDatabase

    # Delete user's tasks
    db.query(Task).filter(Task.user_id == user_id).delete()

    # Delete user's Text2SQL databases
    db.query(Text2SQLDatabase).filter(Text2SQLDatabase.user_id == user_id).delete()

    # 删除系统角色绑定，避免用户删除后留下悬挂成员记录。
    db.query(UserSystemRole).filter(UserSystemRole.user_id == user_id).delete()

    # Delete user's MCP server associations (not the servers themselves)
    db.query(UserMCPServer).filter(UserMCPServer.user_id == user_id).delete()

    # Delete the user (UserModel and UserDefaultModel have cascade delete)
    db.delete(user)
    db.commit()

    return {"message": "User deleted successfully"}
