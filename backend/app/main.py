"""AI 学习助手后端入口。

启动流程：
1. 初始化日志（loguru 控制台 + 文件双输出）
2. 创建数据库表（若不存在）
3. 初始化 4 种预设人格
4. 注册 CORS 中间件与 API 路由
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.common.logger import get_logger, setup_logging
from app.config import get_settings
from app.models.database import Base, engine, get_db
from app.services.persona_service import init_presets

settings = get_settings()

# 1. 初始化日志
setup_logging(log_dir=settings.log_dir, log_level=settings.log_level)
logger = get_logger()
logger.info(f"AI 学习助手启动中... version={__version__}")

# 2. 创建数据库表
Base.metadata.create_all(bind=engine)
logger.info("数据库表已就绪。")

# 3. 初始化预设人格
db = next(get_db())
try:
    init_presets(db)
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


# 6. 业务路由（Task 3 实施后取消注释）
# from app.api.v1 import projects, knowledge_tree, personas, tasks
# app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
# app.include_router(knowledge_tree.router, prefix="/api/v1/knowledge-tree", tags=["knowledge-tree"])
# app.include_router(personas.router, prefix="/api/v1/personas", tags=["personas"])
# app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["tasks"])
