"""学习项目路由：完整 RESTful CRUD 接口。

接口列表：
- POST   /          创建项目
- GET    /          列出当前用户的所有项目
- GET    /{id}      查询单个项目
- PUT    /{id}      更新项目
- DELETE /{id}      删除项目

Note:
    暂无鉴权，user_id 先用常量 ``DEFAULT_USER_ID``，由 main.py 启动时确保该用户存在。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import (
    LearningProjectCreate,
    LearningProjectResponse,
    LearningProjectUpdate,
)
from app.services.project_service import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)

router = APIRouter()

# 暂无鉴权，先用一个固定 user_id；后续接入 JWT 后从 token 解析
DEFAULT_USER_ID = "default-user"


@router.post(
    "/",
    response_model=LearningProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建学习项目",
)
def create(
    project_data: LearningProjectCreate,
    db: Session = Depends(get_db),
) -> LearningProjectResponse:
    """创建一个新的学习项目，归属当前默认用户。"""
    project = create_project(db, DEFAULT_USER_ID, project_data)
    return LearningProjectResponse.model_validate(project)


@router.get(
    "/",
    response_model=list[LearningProjectResponse],
    summary="列出学习项目",
)
def list_all(db: Session = Depends(get_db)) -> list[LearningProjectResponse]:
    """列出当前用户的所有学习项目，按最后活跃时间倒序。"""
    projects = list_projects(db, DEFAULT_USER_ID)
    return [LearningProjectResponse.model_validate(p) for p in projects]


@router.get(
    "/{project_id}",
    response_model=LearningProjectResponse,
    summary="查询单个学习项目",
)
def get_one(project_id: str, db: Session = Depends(get_db)) -> LearningProjectResponse:
    """根据项目 ID 查询详情，不存在或非当前用户项目返回 404。"""
    project = get_project(db, project_id, DEFAULT_USER_ID)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: id={project_id}",
        )
    return LearningProjectResponse.model_validate(project)


@router.put(
    "/{project_id}",
    response_model=LearningProjectResponse,
    summary="更新学习项目",
)
def update(
    project_id: str,
    update_data: LearningProjectUpdate,
    db: Session = Depends(get_db),
) -> LearningProjectResponse:
    """更新项目字段（仅更新非 None 字段），不存在返回 404。"""
    project = update_project(db, project_id, DEFAULT_USER_ID, update_data)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: id={project_id}",
        )
    return LearningProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除学习项目",
)
def delete(project_id: str, db: Session = Depends(get_db)) -> None:
    """删除项目（级联删除其下知识点、节点、任务、消息），不存在返回 404。"""
    success = delete_project(db, project_id, DEFAULT_USER_ID)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目不存在: id={project_id}",
        )
