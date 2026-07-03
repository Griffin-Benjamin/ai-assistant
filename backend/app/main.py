"""AI 学习助手后端入口。

启动流程：
1. 初始化日志（loguru 控制台 + 文件双输出）
2. 创建数据库表（若不存在）
3. 初始化 4 种预设人格
4. 确保默认用户存在（暂无鉴权，projects 等业务接口使用 default-user）
5. 注册 CORS 中间件与 API 路由
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import __version__
from app.api.v1 import knowledge_tree, personas, projects, tasks
from app.common.logger import get_logger, setup_logging
from app.config import get_settings
from app.models.database import Base, engine, get_db
from app.models.schemas import User
from app.services.persona_service import init_presets

settings = get_settings()

# 1. 初始化日志
setup_logging(log_dir=settings.log_dir, log_level=settings.log_level)
logger = get_logger()
logger.info(f"AI 学习助手启动中... version={__version__}")


def _ensure_default_user(session: Session) -> None:
    """确保默认用户存在（暂无鉴权，业务接口用 default-user 作为占位 user_id）。

    Args:
        session: 数据库会话。
    """
    existing = session.query(User).filter(User.id == "default-user").first()
    if existing is not None:
        logger.debug("默认用户 default-user 已存在，跳过创建。")
        return
    default_user = User(
        id="default-user",
        email="default@example.com",
        password_hash="dev",
    )
    session.add(default_user)
    session.commit()
    logger.info("已创建默认用户 default-user。")


# 2. 创建数据库表
Base.metadata.create_all(bind=engine)
logger.info("数据库表已就绪。")

# 3. 初始化预设人格 + 确保默认用户存在
db: Session = next(get_db())
try:
    init_presets(db)
    _ensure_default_user(db)
finally:
    db.close()

# 4. FastAPI 实例
app = FastAPI(
    title="AI 学习助手",
    version=__version__,
    description="LangChain + LangGraph 驱动的个性化学习助手，支持用户风格克隆与三库分离",
)

# 5. CORS（前端 Web 端运行在 3782 端口）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3782",
        "http://127.0.0.1:3782",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["meta"])
def health_check() -> dict:
    """健康检查端点。"""
    return {"status": "ok", "version": __version__}


# 6. 业务路由
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(knowledge_tree.router, prefix="/api/v1/knowledge-tree", tags=["knowledge-tree"])
app.include_router(personas.router, prefix="/api/v1/personas", tags=["personas"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
