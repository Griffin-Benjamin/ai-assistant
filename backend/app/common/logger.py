"""loguru 日志配置：控制台 + 文件双输出。

提供 ``setup_logging`` 与 ``get_logger`` 两个入口：
- ``setup_logging`` 在应用启动时调用一次，完成 handler 注册；
- ``get_logger`` 在任意模块调用，返回全局 logger 单例。
"""
import sys
from pathlib import Path

from loguru import logger as _loguru

# 模块级标志：避免重复注册 handler
_initialized: bool = False


def setup_logging(log_dir: str = "./logs", log_level: str = "INFO") -> None:
    """初始化 loguru 日志系统。

    Args:
        log_dir: 日志文件输出目录，不存在则自动创建。
        log_level: 日志级别，如 ``"INFO"``、``"DEBUG"``。

    Note:
        本函数应只调用一次；重复调用会先清空已有 handler 再重新注册。
    """
    global _initialized

    _loguru.remove()

    # 控制台输出（带颜色）
    _loguru.add(
        sys.stdout,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # 文件输出（带滚动）
    log_path = Path(log_dir).resolve()
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "app.log"
    _loguru.add(
        str(log_file),
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        rotation="10 MB",
        retention="7 days",
        compression=None,
        encoding="utf-8",
        enqueue=True,  # 多线程安全
    )

    _initialized = True


def get_logger():
    """返回全局 loguru logger 单例。

    Returns:
        loguru.logger: 全局 logger 对象。若未调用过 ``setup_logging``，
        会自动以默认参数初始化一次，确保 logger 可用。
    """
    if not _initialized:
        setup_logging()
    return _loguru
