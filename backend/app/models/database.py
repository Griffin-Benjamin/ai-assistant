"""SQLAlchemy 数据库引擎与会话管理（MySQL）。

提供：
- ``engine``：全局 SQLAlchemy 引擎（MySQL，启用 pool_pre_ping 防止连接断开）
- ``SessionLocal``：会话工厂
- ``Base``：所有 ORM 模型的基类
- ``get_db``：FastAPI 依赖注入函数
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# MySQL 不需要 check_same_thread；空 connect_args 即可
# pool_pre_ping=True：每次借出连接前 ping 一下，避免拿到已断开的连接
# pool_recycle=3600：连接闲置 1 小时后回收，防止 MySQL wait_timeout 主动断开
engine = create_engine(
    settings.database_url,
    connect_args={},
    pool_pre_ping=True,
    pool_recycle=3600,
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
