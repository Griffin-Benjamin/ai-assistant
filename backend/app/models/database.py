"""SQLAlchemy 数据库引擎与会话管理。

提供：
- ``engine``：全局 SQLAlchemy 引擎（SQLite，关闭跨线程检查以支持 FastAPI 线程池）
- ``SessionLocal``：会话工厂
- ``Base``：所有 ORM 模型的基类
- ``get_db``：FastAPI 依赖注入函数
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# SQLite 需要关闭 check_same_thread，否则 FastAPI 的线程池会报错
connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入：提供一个数据库会话并在请求结束后关闭。

    Yields:
        Session: SQLAlchemy 会话对象。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
