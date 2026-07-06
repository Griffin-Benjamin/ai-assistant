"""SQLAlchemy 数据库引擎与会话管理（SQLite）。

提供：
- ``engine``：全局 SQLAlchemy 引擎（SQLite）
- ``SessionLocal``：会话工厂
- ``Base``：所有 ORM 模型的基类
- ``get_db``：FastAPI 依赖注入函数
"""
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# 确保 SQLite 数据文件所在目录存在
_db_path = Path(settings.database_url.replace("sqlite:///", ""))
_db_path.parent.mkdir(parents=True, exist_ok=True)

# SQLite 特有：check_same_thread=False 让多线程共享连接（FastAPI 多请求需要）
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
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
