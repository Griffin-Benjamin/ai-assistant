"""数据模型：SQLAlchemy ORM 模型 + Pydantic 请求/响应 Schema。

本模块定义 AI 学习助手的全部持久化模型与 API 数据结构。

三库分离架构：
- ``KnowledgeItem``  -> kb_facts  （客观知识点）
- ``UserStyle``      -> kb_style  （用户语言风格样本）
- ``UserThinking``   -> kb_thinking（用户推理路径样本）

JSON 字段说明：
所有 ``*ids`` / ``capabilities`` / ``tags`` / ``task_config`` / ``parsed_prompt``
等结构化字段均以 ``String`` 存储 JSON 文本，读写时用 ``json.loads`` / ``json.dumps``
转换。这样可保持 SQLite / MySQL 兼容性，避免方言差异。

Note:
    MySQL 的 VARCHAR 必须显式指定长度，因此所有 ``String`` 列都带长度参数
    （SQLite 会忽略该长度，不影响测试）。
"""
import json
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.database import Base


def _new_uuid() -> str:
    """生成新的 UUID 字符串。"""
    return str(uuid.uuid4())


# ============================================================
# SQLAlchemy ORM 模型
# ============================================================

class User(Base):
    """用户表。"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    projects = relationship("LearningProject", back_populates="user", cascade="all, delete-orphan")
    personas = relationship("Persona", back_populates="user", cascade="all, delete-orphan")
    model_configs = relationship("ModelConfig", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")


class ModelConfig(Base):
    """用户模型配置（支持用户自选模型）。"""

    __tablename__ = "model_configs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # openai/deepseek/claude/qwen
    base_url = Column(String(512), nullable=False)
    api_key = Column(String(255), nullable=False)  # 加密存储
    model_name = Column(String(100), nullable=False)
    max_context = Column(Integer, default=8192)
    # JSON string: ["tool_calling", "vision", "streaming"]
    capabilities = Column(String(1000), default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="model_configs")


class LearningProject(Base):
    """学习项目。"""

    __tablename__ = "learning_projects"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(20), default="#4F46E5")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="projects")
    knowledge_items = relationship("KnowledgeItem", back_populates="project", cascade="all, delete-orphan")
    knowledge_nodes = relationship("KnowledgeNode", back_populates="project", cascade="all, delete-orphan")
    scheduled_tasks = relationship("ScheduledTask", back_populates="project", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="project", cascade="all, delete-orphan")


class KnowledgeNode(Base):
    """知识树节点。"""

    __tablename__ = "knowledge_nodes"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    project_id = Column(String(36), ForeignKey("learning_projects.id"), nullable=False, index=True)
    parent_id = Column(String(36), ForeignKey("knowledge_nodes.id"), nullable=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, default=0)
    mastery_level = Column(String(30), default="not_started")  # not_started/learning/mastered
    # JSON string list of KnowledgeItem ids
    linked_facts_ids = Column(String(4000), default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("LearningProject", back_populates="knowledge_nodes")
    parent = relationship(
        "KnowledgeNode",
        remote_side="KnowledgeNode.id",
        back_populates="children",
    )
    children = relationship("KnowledgeNode", back_populates="parent", cascade="all, delete-orphan")


class KnowledgeItem(Base):
    """客观知识点（kb_facts）。"""

    __tablename__ = "knowledge_items"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("learning_projects.id"), nullable=False, index=True)
    linked_node_id = Column(String(36), ForeignKey("knowledge_nodes.id"), nullable=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    subject = Column(String(100), nullable=True)
    # JSON string list of tags
    tags = Column(String(1000), nullable=True)
    source = Column(String(30), default="manual")  # manual/auto/detected
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("LearningProject", back_populates="knowledge_items")


class UserStyle(Base):
    """用户语言风格样本（kb_style）。"""

    __tablename__ = "user_styles"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    phrase = Column(String(200), nullable=False)
    context = Column(Text, nullable=True)
    frequency = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    last_used = Column(DateTime, default=datetime.utcnow)


class UserThinking(Base):
    """用户推理路径样本（kb_thinking）。"""

    __tablename__ = "user_thinkings"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    pattern = Column(String(200), nullable=False)
    example = Column(Text, nullable=True)
    applicability = Column(String(100), nullable=True)
    confidence = Column(Float, default=0.5)
    last_used = Column(DateTime, default=datetime.utcnow)


class Persona(Base):
    """人格（导师风格）。"""

    __tablename__ = "personas"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    # 预设人格不属于任何用户，故允许 NULL；自定义人格必须归属用户
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String(30), nullable=False)  # preset/imported_md/custom
    source_content = Column(Text, nullable=True)
    # JSON string: {"role": ..., "speaking_style": ..., "teaching_preferences": ...}
    parsed_prompt = Column(Text, nullable=True)
    is_preset = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="personas")
    messages = relationship("Message", back_populates="persona")


class ScheduledTask(Base):
    """定时任务。"""

    __tablename__ = "scheduled_tasks"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("learning_projects.id"), nullable=True)
    name = Column(String(100), nullable=False)
    cron_expr = Column(String(50), nullable=False)
    task_type = Column(String(30), nullable=False)  # summarize/review_reminder/custom
    # JSON string of task config
    task_config = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("LearningProject", back_populates="scheduled_tasks")


class Message(Base):
    """对话消息。"""

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    thread_id = Column(String(100), index=True, nullable=False)
    role = Column(String(20), nullable=False)  # user/assistant/tool
    content = Column(Text, nullable=False)
    # lecture/definition/example_question/chat/answer/tool_result/summary
    message_type = Column(String(30), default="chat")
    project_id = Column(String(36), ForeignKey("learning_projects.id"), nullable=True)
    persona_id = Column(String(36), ForeignKey("personas.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")
    project = relationship("LearningProject", back_populates="messages")
    persona = relationship("Persona", back_populates="messages")


# ============================================================
# Pydantic 请求/响应 Schema
# ============================================================

# ---------- LearningProject ----------

class LearningProjectCreate(BaseModel):
    """创建学习项目请求。"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    color: str = "#4F46E5"


class LearningProjectUpdate(BaseModel):
    """更新学习项目请求。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    color: str | None = None


class LearningProjectResponse(BaseModel):
    """学习项目响应。"""
    id: str
    user_id: str
    name: str
    description: str | None
    color: str
    created_at: datetime
    last_active_at: datetime

    model_config = {"from_attributes": True}


# ---------- KnowledgeNode ----------

class KnowledgeNodeCreate(BaseModel):
    """创建知识树节点请求。"""
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    parent_id: str | None = None
    order: int = 0


class KnowledgeNodeUpdate(BaseModel):
    """更新知识树节点请求。"""
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    order: int | None = None


class KnowledgeNodeResponse(BaseModel):
    """知识树节点响应。"""
    id: str
    project_id: str
    parent_id: str | None
    title: str
    description: str | None
    order: int
    mastery_level: str
    linked_facts_ids: list[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_node(cls, node: "KnowledgeNode") -> "KnowledgeNodeResponse":
        """从 ORM 对象构造响应，自动解析 linked_facts_ids JSON。"""
        try:
            facts_ids = json.loads(node.linked_facts_ids) if node.linked_facts_ids else []
        except (json.JSONDecodeError, TypeError):
            facts_ids = []
        return cls(
            id=node.id,
            project_id=node.project_id,
            parent_id=node.parent_id,
            title=node.title,
            description=node.description,
            order=node.order,
            mastery_level=node.mastery_level,
            linked_facts_ids=facts_ids,
            created_at=node.created_at,
        )


# ---------- Persona ----------

class PersonaCreate(BaseModel):
    """创建人格请求。"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    source_type: str = Field(default="custom", description="preset/imported_md/custom")
    source_content: str | None = None
    parsed_prompt: str | None = None


class PersonaUpdate(BaseModel):
    """更新人格请求。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    parsed_prompt: str | None = None


class PersonaResponse(BaseModel):
    """人格响应。"""
    id: str
    user_id: str
    name: str
    description: str | None
    source_type: str
    source_content: str | None
    parsed_prompt: str | None
    is_preset: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- ScheduledTask ----------

class ScheduledTaskCreate(BaseModel):
    """创建定时任务请求。"""
    name: str = Field(..., min_length=1, max_length=100)
    cron_expr: str = Field(..., description="标准 5 段 cron 表达式")
    task_type: str = Field(..., description="summarize/review_reminder/custom")
    task_config: str | None = "{}"
    project_id: str | None = None


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求。"""
    name: str | None = None
    cron_expr: str | None = None
    task_type: str | None = None
    task_config: str | None = None
    project_id: str | None = None


class ScheduledTaskResponse(BaseModel):
    """定时任务响应。"""
    id: str
    user_id: str
    project_id: str | None
    name: str
    cron_expr: str
    task_type: str
    task_config: str
    is_active: bool
    last_run_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- KnowledgeItem ----------

class KnowledgeItemCreate(BaseModel):
    """创建知识点请求。"""
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    subject: str | None = None
    tags: list[str] | None = None
    source: str = "manual"
    linked_node_id: str | None = None


class KnowledgeItemResponse(BaseModel):
    """知识点响应。"""
    id: str
    user_id: str
    project_id: str
    linked_node_id: str | None
    title: str
    content: str
    subject: str | None
    tags: list[str] = []
    source: str
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_item(cls, item: "KnowledgeItem") -> "KnowledgeItemResponse":
        """从 ORM 对象构造响应，自动解析 tags JSON。"""
        try:
            tags = json.loads(item.tags) if item.tags else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        return cls(
            id=item.id,
            user_id=item.user_id,
            project_id=item.project_id,
            linked_node_id=item.linked_node_id,
            title=item.title,
            content=item.content,
            subject=item.subject,
            tags=tags,
            source=item.source,
            confidence=item.confidence,
            created_at=item.created_at,
        )
