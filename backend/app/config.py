"""应用配置：从 .env 读取并校验。

使用 pydantic-settings，所有敏感信息（API key、密钥）必须通过环境变量
或 .env 文件提供，禁止硬编码在源码中。
"""
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 先把 .env 所有变量加载到 os.environ，让 LangChain/LangSmith 能自动读到
# （pydantic-settings 只填充 Settings 字段，不会泄露其他变量到 os.environ）
load_dotenv()


class Settings(BaseSettings):
    """全局配置项。

    从项目根目录的 .env 文件读取，字段名大小写不敏感。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ========== 数据库 ==========
    database_url: str = Field(
        default="sqlite:///./data/ai_assistant.db",
        description="SQLite 数据库连接串（开发用，生产可换 Postgres）",
    )

    # ========== LLM 模型配置 ==========
    llm_api_key: str = Field(
        default="",
        description="模型 Provider 的 API Key，使用对话功能时必填",
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        description="模型服务的 Base URL（OpenAI 兼容协议）",
    )
    llm_model_name: str = Field(
        default="deepseek-chat",
        description="默认模型名称",
    )

    # ========== 安全 ==========
    secret_key: str = Field(
        default="please-change-me-in-production",
        description="JWT 签名密钥，生产环境必须替换",
    )

    # ========== 上传 ==========
    upload_dir: str = Field(
        default="./uploads",
        description="文件上传目录",
    )

    # ========== 日志 ==========
    log_dir: str = Field(
        default="./logs",
        description="日志输出目录",
    )
    log_level: str = Field(
        default="INFO",
        description="日志级别",
    )

    # ========== LangSmith 追踪 ==========
    langsmith_api_key: str = Field(
        default="",
        description="LangSmith API Key，用于 Agent 调用链路追踪（留空则不上报）",
    )
    langsmith_tracing: bool = Field(
        default=False,
        description="是否开启 LangSmith 追踪，true 开启",
    )
    langsmith_project: str = Field(
        default="ai-assistant",
        description="LangSmith 项目名，用于在 GUI 分组查看",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取并缓存全局配置。

    Returns:
        Settings: 单例配置对象。

    Note:
        使用 lru_cache 保证全局只读取一次 .env，避免重复 IO。
    """
    return Settings()
