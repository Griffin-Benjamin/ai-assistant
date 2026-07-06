"""RAG 检索工具集（Day 6：Agentic RAG）。

提供：
- ``search_knowledge_base``：从 kb_facts 检索客观知识点（@tool 装饰）

Agentic RAG vs 2-Step RAG：
    2-Step RAG：用户问题 → 检索 → 拼到 prompt → LLM 回答（流程固定）
    Agentic RAG：用户问题 → LLM 自主决定是否检索 → 调工具检索 → 看结果是否够
                 → 不够再检索（可换关键词） → 够了回答（流程灵活）

为什么选 Agentic RAG（本项目）：
    1. 用户问"今天天气怎么样"不需要检索知识库（闲聊）
    2. 用户问"什么是装饰器"需要检索
    3. 用户问"Python 怎么给函数加功能"（同义不同表述）需要检索
    4. LLM 可以根据第一次检索结果决定是否再检索（查询重写）
    5. Agent 可以调用多个工具（kb_facts + 未来 Tavily 联网搜索）

工具调用流程：
    用户问题 → LLM 决定调 search_knowledge_base(query=...)
    → 工具返回检索结果（list[Document] 的文本拼接）
    → LLM 看结果生成最终回答（或决定再调一次工具，换 query）
"""
from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.tools import tool
from loguru import logger

from app.services.kb_manager import kb_manager


@tool
def search_knowledge_base(query: str, k: int = 3) -> str:
    """从用户个人知识库（kb_facts）检索客观知识点。

    适用场景：
    - 用户问之前学过的知识（错题、笔记、心得）
    - 用户问的概念在已上传的学习资料中
    - 需要引用用户自己的笔记内容回答

    不适用场景：
    - 闲聊（如"今天怎么样"）
    - 实时信息（如"现在几点"）
    - 通用知识（如"什么是 Python"）—— 这类直接用 LLM 内置知识回答

    Args:
        query: 检索查询文本，建议是用户问题的核心关键词或同义改写
        k: 返回 top-k 条相关知识点，默认 3 条

    Returns:
        str: 检索到的知识点文本（拼接多条），如果没有匹配返回提示信息

    Example:
        >>> search_knowledge_base.invoke({"query": "Python 装饰器怎么用"})
        '找到 2 条相关知识点：\n1. [Python] Python 的装饰器是...\n2. [Python] @decorator 等价于...'
    """
    logger.info(f"[RAG 工具] 检索 kb_facts：query='{query}', k={k}")

    try:
        docs: list[Document] = kb_manager.search_facts(
            query=query,
            k=k,
            filter={"user_id": "default-user"},  # Day 8 接入认证后从 context 拿
        )
    except Exception as e:
        logger.error(f"[RAG 工具] 检索失败：{e}")
        return f"检索知识库时出错：{e}"

    if not docs:
        logger.info("[RAG 工具] 无匹配知识点")
        return "未在知识库中找到相关知识点。请尝试用不同的关键词，或上传相关学习笔记。"

    # 拼接检索结果成文本（LLM 看的格式）
    lines = [f"找到 {len(docs)} 条相关知识点："]
    for i, doc in enumerate(docs, start=1):
        subject = doc.metadata.get("subject", "未分类")
        tags = doc.metadata.get("tags", "")
        content = doc.page_content.strip()
        # 每条带来源标签，方便 LLM 引用
        tag_str = f" [{subject}]" if subject else ""
        tag_str += f" #{tags}" if tags else ""
        lines.append(f"{i}.{tag_str} {content}")

    result = "\n".join(lines)
    logger.debug(f"[RAG 工具] 检索完成：返回 {len(docs)} 条，{len(result)} 字符")
    return result
