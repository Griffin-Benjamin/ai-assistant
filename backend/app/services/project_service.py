"""学习项目 Service：管理学习项目的 CRUD 与活跃时间更新。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.models.schemas import LearningProject, LearningProjectCreate, LearningProjectUpdate

logger = get_logger()


def create_project(db: Session, user_id: str, project_data: LearningProjectCreate) -> LearningProject:
    """创建学习项目。

    Args:
        db: 数据库会话。
        user_id: 所属用户 ID。
        project_data: 项目创建数据。

    Returns:
        LearningProject: 创建后的项目对象。
    """
    project = LearningProject(
        user_id=user_id,
        name=project_data.name,
        description=project_data.description,
        color=project_data.color,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info(f"创建学习项目: id={project.id}, user_id={user_id}, name={project.name}")
    return project


def get_project(db: Session, project_id: str, user_id: str) -> LearningProject | None:
    """查询单个项目（带用户鉴权）。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
        user_id: 用户 ID，用于校验归属。

    Returns:
        LearningProject | None: 项目对象，不存在或不归属该用户返回 None。
    """
    return db.query(LearningProject).filter(
        LearningProject.id == project_id,
        LearningProject.user_id == user_id,
    ).first()


def list_projects(db: Session, user_id: str) -> list[LearningProject]:
    """列出用户的所有项目，按最后活跃时间倒序。

    Args:
        db: 数据库会话。
        user_id: 用户 ID。

    Returns:
        list[LearningProject]: 项目列表。
    """
    return (
        db.query(LearningProject)
        .filter(LearningProject.user_id == user_id)
        .order_by(LearningProject.last_active_at.desc())
        .all()
    )


def update_project(
    db: Session,
    project_id: str,
    user_id: str,
    update_data: LearningProjectUpdate,
) -> LearningProject | None:
    """更新项目信息（仅更新非 None 字段）。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
        user_id: 用户 ID。
        update_data: 待更新字段。

    Returns:
        LearningProject | None: 更新后的项目，不存在返回 None。
    """
    project = get_project(db, project_id, user_id)
    if project is None:
        return None

    update_fields = update_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    logger.info(f"更新学习项目: id={project_id}, fields={list(update_fields.keys())}")
    return project


def delete_project(db: Session, project_id: str, user_id: str) -> bool:
    """删除项目（级联删除其下知识点、节点、任务、消息）。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
        user_id: 用户 ID。

    Returns:
        bool: 是否删除成功。
    """
    project = get_project(db, project_id, user_id)
    if project is None:
        return False

    db.delete(project)
    db.commit()
    logger.info(f"删除学习项目: id={project_id}, user_id={user_id}")
    return True


def update_last_active(db: Session, project_id: str) -> None:
    """更新项目最后活跃时间为当前时间。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。
    """
    db.query(LearningProject).filter(LearningProject.id == project_id).update(
        {LearningProject.last_active_at: datetime.utcnow()}
    )
    db.commit()
