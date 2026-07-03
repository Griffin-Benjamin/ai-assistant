"""知识树 Service：管理知识树节点的 CRUD、树形构建、进度统计。"""
import json

from sqlalchemy.orm import Session

from app.common.logger import get_logger
from app.models.schemas import (
    KnowledgeItem,
    KnowledgeNode,
    KnowledgeNodeCreate,
    KnowledgeNodeUpdate,
)

logger = get_logger()


def create_node(
    db: Session,
    project_id: str,
    node_data: KnowledgeNodeCreate,
) -> KnowledgeNode:
    """在指定项目下创建知识树节点。

    Args:
        db: 数据库会话。
        project_id: 所属项目 ID。
        node_data: 节点创建数据。

    Returns:
        KnowledgeNode: 创建后的节点。
    """
    node = KnowledgeNode(
        project_id=project_id,
        parent_id=node_data.parent_id,
        title=node_data.title,
        description=node_data.description,
        order=node_data.order,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    logger.info(f"创建知识节点: id={node.id}, project_id={project_id}, title={node.title}")
    return node


def get_node(db: Session, node_id: str) -> KnowledgeNode | None:
    """查询单个节点。

    Args:
        db: 数据库会话。
        node_id: 节点 ID。

    Returns:
        KnowledgeNode | None: 节点对象或 None。
    """
    return db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()


def list_nodes(db: Session, project_id: str) -> list[KnowledgeNode]:
    """列出项目下所有节点（按 order 正序）。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        list[KnowledgeNode]: 节点列表。
    """
    return (
        db.query(KnowledgeNode)
        .filter(KnowledgeNode.project_id == project_id)
        .order_by(KnowledgeNode.order.asc())
        .all()
    )


def get_tree(db: Session, project_id: str) -> dict:
    """构建项目的知识树形结构。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        dict: ``{"nodes": [...]}``，其中每个节点形如::

            {
                "id": ..., "title": ..., "description": ...,
                "order": ..., "mastery_level": ...,
                "linked_facts_ids": [...],
                "children": [...]
            }
    """
    nodes = list_nodes(db, project_id)

    def _build_children(parent_id: str | None) -> list[dict]:
        children = []
        for node in nodes:
            if node.parent_id == parent_id:
                try:
                    facts_ids = json.loads(node.linked_facts_ids) if node.linked_facts_ids else []
                except (json.JSONDecodeError, TypeError):
                    facts_ids = []
                children.append({
                    "id": node.id,
                    "title": node.title,
                    "description": node.description,
                    "order": node.order,
                    "mastery_level": node.mastery_level,
                    "linked_facts_ids": facts_ids,
                    "children": _build_children(node.id),
                })
        return children

    return {"nodes": _build_children(None)}


def update_node(
    db: Session,
    node_id: str,
    update_data: KnowledgeNodeUpdate,
) -> KnowledgeNode | None:
    """更新节点（仅更新非 None 字段）。

    Args:
        db: 数据库会话。
        node_id: 节点 ID。
        update_data: 待更新字段。

    Returns:
        KnowledgeNode | None: 更新后的节点，不存在返回 None。
    """
    node = get_node(db, node_id)
    if node is None:
        return None

    update_fields = update_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(node, field, value)

    db.commit()
    db.refresh(node)
    logger.info(f"更新知识节点: id={node_id}, fields={list(update_fields.keys())}")
    return node


def delete_node(db: Session, node_id: str) -> bool:
    """删除节点（级联删除子节点）。

    Args:
        db: 数据库会话。
        node_id: 节点 ID。

    Returns:
        bool: 是否删除成功。
    """
    node = get_node(db, node_id)
    if node is None:
        return False

    # 解除关联的知识点引用
    db.query(KnowledgeItem).filter(KnowledgeItem.linked_node_id == node_id).update(
        {KnowledgeItem.linked_node_id: None}
    )

    db.delete(node)
    db.commit()
    logger.info(f"删除知识节点: id={node_id}")
    return True


def link_facts_to_node(
    db: Session,
    node_id: str,
    facts_ids: list[str],
) -> KnowledgeNode | None:
    """将知识点列表关联到节点（覆盖原有关联）。

    Args:
        db: 数据库会话。
        node_id: 节点 ID。
        facts_ids: 知识点 ID 列表。

    Returns:
        KnowledgeNode | None: 更新后的节点，不存在返回 None。
    """
    node = get_node(db, node_id)
    if node is None:
        return None

    node.linked_facts_ids = json.dumps(facts_ids)
    db.commit()
    db.refresh(node)
    logger.info(f"节点 {node_id} 关联知识点: {facts_ids}")
    return node


def update_mastery(db: Session, node_id: str, mastery_level: str) -> KnowledgeNode | None:
    """更新节点掌握程度。

    Args:
        db: 数据库会话。
        node_id: 节点 ID。
        mastery_level: 掌握程度，not_started/learning/mastered。

    Returns:
        KnowledgeNode | None: 更新后的节点，不存在返回 None。
    """
    node = get_node(db, node_id)
    if node is None:
        return None

    node.mastery_level = mastery_level
    db.commit()
    db.refresh(node)
    logger.info(f"节点 {node_id} 掌握程度更新为: {mastery_level}")
    return node


def get_progress(db: Session, project_id: str) -> dict:
    """统计项目知识树的整体进度。

    Args:
        db: 数据库会话。
        project_id: 项目 ID。

    Returns:
        dict: ``{"total": int, "mastered": int, "learning": int, "not_started": int}``
    """
    nodes = list_nodes(db, project_id)
    total = len(nodes)
    mastered = sum(1 for n in nodes if n.mastery_level == "mastered")
    learning = sum(1 for n in nodes if n.mastery_level == "learning")
    not_started = sum(1 for n in nodes if n.mastery_level == "not_started")
    return {
        "total": total,
        "mastered": mastered,
        "learning": learning,
        "not_started": not_started,
    }
