"""LLM 抽取服务（Day 8：核心链路真实化）。

提供：
- ``extract_style_with_llm``：用 LLM ``with_structured_output`` 从对话历史抽取用户语言风格
- ``summarize_with_llm``：用 LLM ``with_structured_output`` 从对话历史提取客观知识点

设计要点：
    1. 用 Pydantic 模型定义结构化输出 schema，LLM 强制按 schema 输出
    2. 抽取失败有 fallback：返回 mock 数据 + 警告日志，保证工作流不中断
    3. 模型复用 learning_agent 的 init_chat_model 配置（DeepSeek 兼容 OpenAI）

为什么用 with_structured_output：
    - 比纯 prompt + 字符串解析更可靠（LLM 直接输出 JSON）
    - LangChain 自动把 Pydantic schema 转成 tool，让模型调 tool 输出
    - 解析失败会抛错，可以 catch 后 fallback

Day 8 在工作流中的位置：
    extract_style_node → extract_style_with_llm → 写入 kb_style
    summarize_node     → summarize_with_llm     → 写入 kb_facts
"""
from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from loguru import logger
from pydantic import BaseModel, Field

from app.config import get_settings

settings = get_settings()


# ========== 结构化输出 Schema ==========
class StyleSample(BaseModel):
    """单条风格样本（LLM 强制按此 schema 输出）。"""

    content: str = Field(
        description="用户语言风格样本，如'多用类比'、'用你不用您'、'讲完出 1-2 道自检题'"
    )
    sample_type: str = Field(
        description="样本类型：phrase（短语习惯）/ tone（语气）/ habit（讲解习惯）"
    )
    confidence: float = Field(
        default=0.8,
        description="置信度 0-1，越高表示越确定这是用户的稳定风格",
    )


class StyleExtractionResult(BaseModel):
    """风格抽取结果（LLM 输出的整体结构）。"""

    samples: list[StyleSample] = Field(
        default_factory=list,
        description="从对话历史中抽取出的用户语言风格样本列表",
    )


class KnowledgeFact(BaseModel):
    """单条客观知识点（LLM 强制按此 schema 输出）。"""

    content: str = Field(
        description="客观知识点内容，如'Python 装饰器是高阶函数，@decorator 等价于 func = decorator(func)'"
    )
    subject: str = Field(
        description="学科/领域：Python / FastAPI / LangGraph / general 等"
    )
    tags: str = Field(
        default="",
        description="知识点标签，逗号分隔，如'decorator,high-order-function'",
    )


class SummarizationResult(BaseModel):
    """知识汇总结果（LLM 输出的整体结构）。"""

    facts: list[KnowledgeFact] = Field(
        default_factory=list,
        description="从对话历史中提取出的客观知识点列表",
    )


# ========== 内部工具 ==========
def _build_llm() -> Any:
    """创建 LLM 实例（复用 learning_agent 的配置）。

    Returns:
        ChatModel: 已初始化的 LLM 实例
    """
    return init_chat_model(
        model=settings.llm_model_name,
        model_provider="openai",
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )


def _format_messages_for_llm(messages: list[BaseMessage] | list[dict],
                             max_messages: int = 10) -> str:
    """把消息列表格式化成 LLM 可读的纯文本。

    Args:
        messages: 消息列表（BaseMessage 或 dict）
        max_messages: 最多取最近 N 条（避免 token 爆炸）

    Returns:
        str: 格式化的对话历史文本
    """
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    lines = []
    for msg in recent:
        if hasattr(msg, "type"):
            role = msg.type
            content = msg.content
        elif isinstance(msg, dict):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
        else:
            role = "unknown"
            content = str(msg)
        # 截断过长的单条消息
        if isinstance(content, str) and len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


# ========== 公开 API ==========
async def extract_style_with_llm(
    messages: list[BaseMessage] | list[dict],
    user_id: str = "default-user",
) -> list[Document]:
    """用 LLM 从对话历史抽取用户语言风格样本。

    Args:
        messages: 对话历史（BaseMessage 列表或 dict 列表）
        user_id: 用户 ID（写入 metadata）

    Returns:
        list[Document]: 风格样本文档列表，可直接 add_style_samples 到 kb_style

    工作流程：
        1. 把 messages 格式化成纯文本
        2. 用 with_structured_output(StyleExtractionResult) 让 LLM 输出结构化结果
        3. 转成 Document 列表（带 metadata）
        4. LLM 调用失败 → fallback 返回 mock 样本 + 警告日志

    Example:
        >>> docs = await extract_style_with_llm(messages, user_id="u1")
        >>> kb_manager.add_style_samples(docs)
    """
    if not messages:
        logger.warning("[extract_style_with_llm] messages 为空，返回空列表")
        return []

    conversation_text = _format_messages_for_llm(messages, max_messages=10)
    logger.info(f"[extract_style_with_llm] 开始抽取风格，对话长度 {len(conversation_text)} 字符")

    try:
        llm = _build_llm()
        # method="function_calling"：用工具调用方式输出结构化 JSON
        # DeepSeek 不支持默认的 response_format（json_schema），但支持 function calling
        structured_llm = llm.with_structured_output(
            StyleExtractionResult, method="function_calling"
        )

        prompt = f"""请从以下对话历史中，抽取用户的语言风格样本（不是 AI 的风格，是用户的）。

关注点：
- 用户的用语习惯（多用类比？喜欢问"为什么"？）
- 用户的语气偏好（轻松？正式？）
- 用户的学习习惯（喜欢做题？喜欢看代码？）

对话历史：
{conversation_text}

请输出结构化的风格样本列表。如果对话太短或无明显风格特征，返回空列表。"""

        result: StyleExtractionResult = await structured_llm.ainvoke(prompt)

        docs = [
            Document(
                page_content=s.content,
                metadata={
                    "user_id": user_id,
                    "confidence": s.confidence,
                    "type": s.sample_type,
                    "source": "llm_extracted",
                },
            )
            for s in result.samples
        ]
        logger.info(f"[extract_style_with_llm] LLM 抽取 {len(docs)} 条风格样本")
        return docs

    except Exception as e:
        logger.error(f"[extract_style_with_llm] LLM 抽取失败，fallback 到 mock：{e}")
        # fallback：返回 1 条 mock 样本，保证工作流不中断
        return [
            Document(
                page_content="（fallback）用户偏好简洁回答，喜欢看到代码示例",
                metadata={
                    "user_id": user_id,
                    "confidence": 0.5,
                    "type": "fallback",
                    "source": "llm_failed",
                },
            )
        ]


async def summarize_with_llm(
    messages: list[BaseMessage] | list[dict],
    user_id: str = "default-user",
) -> list[Document]:
    """用 LLM 从对话历史提取客观知识点。

    Args:
        messages: 对话历史
        user_id: 用户 ID

    Returns:
        list[Document]: 知识点文档列表，可直接 add_facts 到 kb_facts

    工作流程：
        1. 把 messages 格式化成纯文本
        2. 用 with_structured_output(SummarizationResult) 让 LLM 输出结构化结果
        3. 转成 Document 列表（带 metadata）
        4. LLM 调用失败 → fallback 返回 mock 知识点 + 警告日志
    """
    if not messages:
        logger.warning("[summarize_with_llm] messages 为空，返回空列表")
        return []

    conversation_text = _format_messages_for_llm(messages, max_messages=20)
    logger.info(f"[summarize_with_llm] 开始汇总知识点，对话长度 {len(conversation_text)} 字符")

    try:
        llm = _build_llm()
        # method="function_calling"：用工具调用方式输出结构化 JSON
        # DeepSeek 不支持默认的 response_format（json_schema），但支持 function calling
        structured_llm = llm.with_structured_output(
            SummarizationResult, method="function_calling"
        )

        prompt = f"""请从以下对话历史中，提取客观知识点（错题、笔记、心得）。

要求：
- 只提取"事实性"知识点（定义、原理、代码用法），不提取闲聊内容
- 每条知识点要完整、自包含（脱离对话上下文也能看懂）
- subject 填学科/领域（Python/FastAPI/LangGraph/general 等）

对话历史：
{conversation_text}

请输出结构化的知识点列表。如果没有可提取的知识点，返回空列表。"""

        result: SummarizationResult = await structured_llm.ainvoke(prompt)

        docs = [
            Document(
                page_content=f.content,
                metadata={
                    "user_id": user_id,
                    "subject": f.subject,
                    "tags": f.tags,
                    "source": "auto_summarize",
                },
            )
            for f in result.facts
        ]
        logger.info(f"[summarize_with_llm] LLM 提取 {len(docs)} 条知识点")
        return docs

    except Exception as e:
        logger.error(f"[summarize_with_llm] LLM 提取失败，fallback 到 mock：{e}")
        return [
            Document(
                page_content="（fallback）用户在本次对话中学习了 LangGraph StateGraph 相关知识",
                metadata={
                    "user_id": user_id,
                    "subject": "LangGraph",
                    "tags": "state,graph",
                    "source": "llm_failed",
                },
            )
        ]
