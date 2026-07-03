"""数据模型与 Service 层测试。

使用内存 SQLite 数据库（StaticPool 保证单连接），隔离生产数据。

覆盖：
1. 数据库表能正确创建
2. LearningProject CRUD 正常
3. KnowledgeNode 树形结构正确
4. Persona 预设初始化正常
5. ScheduledTask CRUD 正常
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.database import Base
from app.models.schemas import (
    KnowledgeItem,
    KnowledgeNode,
    LearningProject,
    Message,
    ModelConfig,
    Persona,
    ScheduledTask,
    User,
    UserStyle,
    UserThinking,
)
from app.models.schemas import (
    KnowledgeItemCreate,
    KnowledgeNodeCreate,
    KnowledgeNodeUpdate,
    LearningProjectCreate,
    LearningProjectUpdate,
    PersonaCreate,
    PersonaUpdate,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from app.services.knowledge_tree_service import (
    create_node,
    delete_node,
    get_node,
    get_progress,
    get_tree,
    link_facts_to_node,
    list_nodes,
    update_mastery,
    update_node,
)
from app.services.persona_service import (
    create_persona,
    delete_persona,
    get_persona,
    init_presets,
    list_personas,
    list_presets,
    update_persona,
)
from app.services.project_service import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)
from app.services.task_service import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    record_run,
    toggle_task,
    update_task,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture(scope="function")
def db_engine():
    """每个测试函数独立的内存 SQLite 引擎。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db(db_engine) -> Session:
    """每个测试函数独立的数据库会话。"""
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_engine,
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def test_user(db: Session) -> User:
    """创建测试用户。"""
    user = User(
        id=str(uuid.uuid4()),
        email="test@example.com",
        password_hash="fake_hash",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ============================================================
# 1. 数据库表创建测试
# ============================================================

class TestTableCreation:
    """验证所有 ORM 模型对应的表能正确创建。"""

    def test_all_tables_exist(self, db_engine):
        """所有表应能正确创建并被 inspector 检测到。"""
        from sqlalchemy import inspect

        inspector = inspect(db_engine)
        table_names = set(inspector.get_table_names())

        expected_tables = {
            "users",
            "model_configs",
            "learning_projects",
            "knowledge_nodes",
            "knowledge_items",
            "user_styles",
            "user_thinkings",
            "personas",
            "scheduled_tasks",
            "messages",
        }
        assert expected_tables.issubset(table_names), (
            f"缺失表: {expected_tables - table_names}"
        )

    def test_user_with_all_relations(self, db: Session, test_user: User):
        """User 创建后能正确关联所有子表。"""
        project = LearningProject(
            user_id=test_user.id,
            name="测试项目",
        )
        db.add(project)
        db.commit()

        persona = Persona(
            user_id=test_user.id,
            name="测试人格",
            source_type="custom",
        )
        db.add(persona)
        db.commit()

        model_config = ModelConfig(
            user_id=test_user.id,
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key="fake_key",
            model_name="deepseek-chat",
        )
        db.add(model_config)
        db.commit()

        message = Message(
            user_id=test_user.id,
            thread_id="thread-1",
            role="user",
            content="你好",
        )
        db.add(message)
        db.commit()

        # 查询验证
        assert len(test_user.projects) == 1
        assert len(test_user.personas) == 1
        assert len(test_user.model_configs) == 1
        assert len(test_user.messages) == 1

    def test_three_kbs_models(self, db: Session, test_user: User):
        """三库分离模型（KnowledgeItem / UserStyle / UserThinking）能独立写入。"""
        project = LearningProject(user_id=test_user.id, name="三库测试")
        db.add(project)
        db.commit()

        # kb_facts
        fact = KnowledgeItem(
            user_id=test_user.id,
            project_id=project.id,
            title="斐波那契数列",
            content="0,1,1,2,3,5,8,...",
            tags='["math", "sequence"]',
        )
        # kb_style
        style = UserStyle(
            user_id=test_user.id,
            phrase="也就是说",
            context="解释概念时的口头禅",
        )
        # kb_thinking
        thinking = UserThinking(
            user_id=test_user.id,
            pattern="从特殊到一般",
            example="先举例再归纳公式",
        )
        db.add_all([fact, style, thinking])
        db.commit()

        assert db.query(KnowledgeItem).count() == 1
        assert db.query(UserStyle).count() == 1
        assert db.query(UserThinking).count() == 1


# ============================================================
# 2. LearningProject CRUD 测试
# ============================================================

class TestProjectCRUD:
    """学习项目增删改查测试。"""

    def test_create_project(self, db: Session, test_user: User):
        """创建项目应成功并返回正确字段。"""
        data = LearningProjectCreate(name="Python 入门", description="学习 Python 基础", color="#FF5733")
        project = create_project(db, test_user.id, data)

        assert project.id is not None
        assert project.user_id == test_user.id
        assert project.name == "Python 入门"
        assert project.description == "学习 Python 基础"
        assert project.color == "#FF5733"
        assert project.created_at is not None

    def test_get_project(self, db: Session, test_user: User):
        """查询项目应返回正确对象，且鉴权生效。"""
        data = LearningProjectCreate(name="测试项目")
        project = create_project(db, test_user.id, data)

        # 正确用户能查到
        found = get_project(db, project.id, test_user.id)
        assert found is not None
        assert found.id == project.id

        # 错误用户查不到
        other_user_id = str(uuid.uuid4())
        not_found = get_project(db, project.id, other_user_id)
        assert not_found is None

    def test_list_projects(self, db: Session, test_user: User):
        """列出项目应返回用户的所有项目。"""
        create_project(db, test_user.id, LearningProjectCreate(name="项目A"))
        create_project(db, test_user.id, LearningProjectCreate(name="项目B"))

        projects = list_projects(db, test_user.id)
        assert len(projects) == 2

    def test_update_project(self, db: Session, test_user: User):
        """更新项目应仅修改提供的字段。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="原名", color="#000000"))
        update_data = LearningProjectUpdate(name="新名")
        updated = update_project(db, project.id, test_user.id, update_data)

        assert updated.name == "新名"
        assert updated.color == "#000000"  # 未提供字段保持不变

    def test_delete_project(self, db: Session, test_user: User):
        """删除项目后应查不到，且级联删除子数据。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="待删除"))
        node = create_node(db, project.id, KnowledgeNodeCreate(title="节点"))

        result = delete_project(db, project.id, test_user.id)
        assert result is True

        assert get_project(db, project.id, test_user.id) is None
        # 级联删除的节点也应不存在
        assert get_node(db, node.id) is None

    def test_update_last_active(self, db: Session, test_user: User):
        """更新活跃时间应改变 last_active_at 字段。"""
        from datetime import datetime, timedelta

        project = create_project(db, test_user.id, LearningProjectCreate(name="活跃测试"))
        old_active = project.last_active_at

        # 模拟旧时间
        project.last_active_at = datetime.utcnow() - timedelta(days=1)
        db.commit()

        from app.services.project_service import update_last_active
        update_last_active(db, project.id)
        db.refresh(project)

        assert project.last_active_at > old_active


# ============================================================
# 3. KnowledgeNode 树形结构测试
# ============================================================

class TestKnowledgeTree:
    """知识树节点 CRUD 与树形构建测试。"""

    def test_create_node(self, db: Session, test_user: User):
        """创建节点应成功。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="树测试"))
        node = create_node(db, project.id, KnowledgeNodeCreate(title="根节点", order=0))

        assert node.id is not None
        assert node.project_id == project.id
        assert node.parent_id is None
        assert node.mastery_level == "not_started"
        assert node.linked_facts_ids == "[]"

    def test_tree_structure(self, db: Session, test_user: User):
        """树形结构应正确反映父子关系。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="树结构"))
        root = create_node(db, project.id, KnowledgeNodeCreate(title="根"))
        child1 = create_node(
            db, project.id, KnowledgeNodeCreate(title="子1", parent_id=root.id)
        )
        child2 = create_node(
            db, project.id, KnowledgeNodeCreate(title="子2", parent_id=root.id)
        )
        grandchild = create_node(
            db, project.id, KnowledgeNodeCreate(title="孙", parent_id=child1.id)
        )

        tree = get_tree(db, project.id)
        nodes = tree["nodes"]

        assert len(nodes) == 1
        assert nodes[0]["title"] == "根"
        assert len(nodes[0]["children"]) == 2
        # 子1 下有孙节点
        child1_dict = next(c for c in nodes[0]["children"] if c["title"] == "子1")
        assert len(child1_dict["children"]) == 1
        assert child1_dict["children"][0]["title"] == "孙"

    def test_update_node(self, db: Session, test_user: User):
        """更新节点应仅修改提供的字段。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="更新测试"))
        node = create_node(db, project.id, KnowledgeNodeCreate(title="原标题", order=0))

        updated = update_node(db, node.id, KnowledgeNodeUpdate(title="新标题"))
        assert updated.title == "新标题"
        assert updated.order == 0  # 未提供字段不变

    def test_delete_node(self, db: Session, test_user: User):
        """删除节点应级联删除子节点。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="删除测试"))
        parent = create_node(db, project.id, KnowledgeNodeCreate(title="父"))
        child = create_node(
            db, project.id, KnowledgeNodeCreate(title="子", parent_id=parent.id)
        )

        result = delete_node(db, parent.id)
        assert result is True
        assert get_node(db, parent.id) is None
        assert get_node(db, child.id) is None  # 级联删除

    def test_link_facts_to_node(self, db: Session, test_user: User):
        """关联知识点到节点应正确写入 JSON。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="关联测试"))
        node = create_node(db, project.id, KnowledgeNodeCreate(title="节点"))

        # 创建两个知识点
        fact1 = KnowledgeItem(
            user_id=test_user.id, project_id=project.id, title="知识点1", content="内容1"
        )
        fact2 = KnowledgeItem(
            user_id=test_user.id, project_id=project.id, title="知识点2", content="内容2"
        )
        db.add_all([fact1, fact2])
        db.commit()

        updated = link_facts_to_node(db, node.id, [fact1.id, fact2.id])
        import json
        assert json.loads(updated.linked_facts_ids) == [fact1.id, fact2.id]

    def test_update_mastery(self, db: Session, test_user: User):
        """更新掌握程度应正确写入。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="掌握测试"))
        node = create_node(db, project.id, KnowledgeNodeCreate(title="节点"))

        updated = update_mastery(db, node.id, "mastered")
        assert updated.mastery_level == "mastered"

    def test_get_progress(self, db: Session, test_user: User):
        """进度统计应正确反映各状态数量。"""
        project = create_project(db, test_user.id, LearningProjectCreate(name="进度测试"))
        n1 = create_node(db, project.id, KnowledgeNodeCreate(title="n1"))
        n2 = create_node(db, project.id, KnowledgeNodeCreate(title="n2"))
        n3 = create_node(db, project.id, KnowledgeNodeCreate(title="n3"))
        update_mastery(db, n1.id, "mastered")
        update_mastery(db, n2.id, "learning")

        progress = get_progress(db, project.id)
        assert progress["total"] == 3
        assert progress["mastered"] == 1
        assert progress["learning"] == 1
        assert progress["not_started"] == 1


# ============================================================
# 4. Persona 预设初始化测试
# ============================================================

class TestPersonaPresets:
    """人格预设初始化与 CRUD 测试。"""

    def test_init_presets(self, db: Session):
        """初始化应创建 4 种预设人格。"""
        init_presets(db)

        presets = list_presets(db)
        assert len(presets) == 4

        names = {p.name for p in presets}
        assert "严格导师" in names
        assert "鼓励型搭子" in names
        assert "苏格拉底式" in names
        assert "费曼讲解员" in names

        # 预设人格 is_preset 应为 True
        for p in presets:
            assert p.is_preset is True
            assert p.source_type == "preset"

    def test_init_presets_idempotent(self, db: Session):
        """重复初始化应是幂等的，不会重复创建。"""
        init_presets(db)
        init_presets(db)

        presets = list_presets(db)
        assert len(presets) == 4

    def test_list_personas_includes_presets(self, db: Session, test_user: User):
        """列出用户人格时应包含预设人格。"""
        init_presets(db)

        # 用户创建一个自定义人格
        create_persona(
            db, test_user.id, PersonaCreate(name="我的专属人格", source_type="custom")
        )

        personas = list_personas(db, test_user.id)
        assert len(personas) == 5  # 4 预设 + 1 自定义

    def test_create_and_get_persona(self, db: Session, test_user: User):
        """创建自定义人格后能正确查询。"""
        persona = create_persona(
            db,
            test_user.id,
            PersonaCreate(
                name="自定义导师",
                description="我的专属风格",
                source_type="custom",
                parsed_prompt='{"role": "test"}',
            ),
        )

        found = get_persona(db, persona.id, test_user.id)
        assert found is not None
        assert found.name == "自定义导师"
        assert found.is_preset is False

    def test_update_persona(self, db: Session, test_user: User):
        """更新自定义人格应成功，预设人格不可更新。"""
        persona = create_persona(
            db, test_user.id, PersonaCreate(name="原名", source_type="custom")
        )
        updated = update_persona(
            db, persona.id, test_user.id, PersonaUpdate(name="新名")
        )
        assert updated.name == "新名"

    def test_update_preset_persona_fails(self, db: Session, test_user: User):
        """更新预设人格应返回 None。"""
        init_presets(db)
        preset = list_presets(db)[0]

        result = update_persona(
            db, preset.id, test_user.id, PersonaUpdate(name="改名")
        )
        assert result is None

    def test_delete_persona(self, db: Session, test_user: User):
        """删除自定义人格应成功，预设人格不可删除。"""
        persona = create_persona(
            db, test_user.id, PersonaCreate(name="待删除", source_type="custom")
        )
        result = delete_persona(db, persona.id, test_user.id)
        assert result is True
        assert get_persona(db, persona.id, test_user.id) is None

    def test_delete_preset_persona_fails(self, db: Session, test_user: User):
        """删除预设人格应返回 False。"""
        init_presets(db)
        preset = list_presets(db)[0]

        result = delete_persona(db, preset.id, test_user.id)
        assert result is False


# ============================================================
# 5. ScheduledTask CRUD 测试
# ============================================================

class TestScheduledTaskCRUD:
    """定时任务增删改查测试。"""

    def test_create_task(self, db: Session, test_user: User):
        """创建任务应成功。"""
        data = ScheduledTaskCreate(
            name="每日汇总",
            cron_expr="0 22 * * *",
            task_type="summarize",
            task_config='{"target": "daily"}',
        )
        task = create_task(db, test_user.id, data)

        assert task.id is not None
        assert task.user_id == test_user.id
        assert task.name == "每日汇总"
        assert task.is_active is True

    def test_get_task(self, db: Session, test_user: User):
        """查询任务应带鉴权。"""
        task = create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="任务", cron_expr="0 * * * *", task_type="custom"),
        )

        found = get_task(db, task.id, test_user.id)
        assert found is not None

        # 错误用户查不到
        other = str(uuid.uuid4())
        assert get_task(db, task.id, other) is None

    def test_list_tasks(self, db: Session, test_user: User):
        """列出任务应返回用户所有任务。"""
        create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="任务1", cron_expr="0 * * * *", task_type="custom"),
        )
        create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="任务2", cron_expr="0 * * * *", task_type="custom"),
        )

        tasks = list_tasks(db, test_user.id)
        assert len(tasks) == 2

    def test_update_task(self, db: Session, test_user: User):
        """更新任务应仅修改提供的字段。"""
        task = create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="原名", cron_expr="0 * * * *", task_type="custom"),
        )
        updated = update_task(
            db, task.id, test_user.id,
            ScheduledTaskUpdate(name="新名"),
        )
        assert updated.name == "新名"
        assert updated.cron_expr == "0 * * * *"  # 未改字段不变

    def test_delete_task(self, db: Session, test_user: User):
        """删除任务后应查不到。"""
        task = create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="待删除", cron_expr="0 * * * *", task_type="custom"),
        )
        result = delete_task(db, task.id, test_user.id)
        assert result is True
        assert get_task(db, task.id, test_user.id) is None

    def test_toggle_task(self, db: Session, test_user: User):
        """停用/启用任务应正确切换状态。"""
        task = create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="切换测试", cron_expr="0 * * * *", task_type="custom"),
        )
        assert task.is_active is True

        disabled = toggle_task(db, task.id, test_user.id, is_active=False)
        assert disabled.is_active is False

        enabled = toggle_task(db, task.id, test_user.id, is_active=True)
        assert enabled.is_active is True

    def test_record_run(self, db: Session, test_user: User):
        """记录运行应更新 last_run_at。"""
        task = create_task(
            db, test_user.id,
            ScheduledTaskCreate(name="运行记录", cron_expr="0 * * * *", task_type="custom"),
        )
        assert task.last_run_at is None

        record_run(db, task.id, success=True, result_summary="执行成功")
        db.refresh(task)
        assert task.last_run_at is not None
