"""定时任务 Service：管理定时汇总/复习提醒任务的 CRUD 与运行记录。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.models.schemas import ScheduledTask, ScheduledTaskCreate, ScheduledTaskUpdate

logger = get_logger()


def create_task(db: Session, user_id: str, task_data: ScheduledTaskCreate) -> ScheduledTask:
    """创建定时任务。

    Args:
        db: 数据库会话。
        user_id: 所属用户 ID。
        task_data: 任务创建数据。

    Returns:
        ScheduledTask: 创建后的任务对象。
    """
    task = ScheduledTask(
        user_id=user_id,
        project_id=task_data.project_id,
        name=task_data.name,
        cron_expr=task_data.cron_expr,
        task_type=task_data.task_type,
        task_config=task_data.task_config or "{}",
        is_active=True,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info(f"创建定时任务: id={task.id}, user_id={user_id}, name={task.name}, type={task.task_type}")
    return task


def get_task(db: Session, task_id: str, user_id: str) -> ScheduledTask | None:
    """查询单个任务（带用户鉴权）。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。
        user_id: 用户 ID。

    Returns:
        ScheduledTask | None: 任务对象或 None。
    """
    return db.query(ScheduledTask).filter(
        ScheduledTask.id == task_id,
        ScheduledTask.user_id == user_id,
    ).first()


def list_tasks(db: Session, user_id: str) -> list[ScheduledTask]:
    """列出用户的所有任务，按创建时间倒序。

    Args:
        db: 数据库会话。
        user_id: 用户 ID。

    Returns:
        list[ScheduledTask]: 任务列表。
    """
    return (
        db.query(ScheduledTask)
        .filter(ScheduledTask.user_id == user_id)
        .order_by(ScheduledTask.created_at.desc())
        .all()
    )


def update_task(
    db: Session,
    task_id: str,
    user_id: str,
    update_data: ScheduledTaskUpdate,
) -> ScheduledTask | None:
    """更新任务（仅更新非 None 字段）。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。
        user_id: 用户 ID。
        update_data: 待更新字段。

    Returns:
        ScheduledTask | None: 更新后的任务，不存在返回 None。
    """
    task = get_task(db, task_id, user_id)
    if task is None:
        return None

    update_fields = update_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    logger.info(f"更新定时任务: id={task_id}, fields={list(update_fields.keys())}")
    return task


def delete_task(db: Session, task_id: str, user_id: str) -> bool:
    """删除任务。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。
        user_id: 用户 ID。

    Returns:
        bool: 是否删除成功。
    """
    task = get_task(db, task_id, user_id)
    if task is None:
        return False

    db.delete(task)
    db.commit()
    logger.info(f"删除定时任务: id={task_id}, user_id={user_id}")
    return True


def toggle_task(db: Session, task_id: str, user_id: str, is_active: bool) -> ScheduledTask | None:
    """启用或停用任务。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。
        user_id: 用户 ID。
        is_active: 目标状态，True 启用 / False 停用。

    Returns:
        ScheduledTask | None: 更新后的任务，不存在返回 None。
    """
    task = get_task(db, task_id, user_id)
    if task is None:
        return None

    task.is_active = is_active
    db.commit()
    db.refresh(task)
    logger.info(f"定时任务 {task_id} 状态切换为: {'启用' if is_active else '停用'}")
    return task


def record_run(db: Session, task_id: str, success: bool, result_summary: str) -> None:
    """记录任务一次执行的结果。

    Args:
        db: 数据库会话。
        task_id: 任务 ID。
        success: 是否执行成功。
        result_summary: 执行结果摘要文本。
    """
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    if task is None:
        logger.warning(f"记录运行结果失败：任务 {task_id} 不存在。")
        return

    task.last_run_at = datetime.utcnow()
    db.commit()
    logger.info(
        f"定时任务 {task_id} 运行记录: success={success}, summary={result_summary[:80]}"
    )
