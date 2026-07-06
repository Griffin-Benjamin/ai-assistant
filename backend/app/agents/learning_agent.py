"""学习助手 Agent 核心模块。

提供：
- ``SYSTEM_PROMPT``：学习助手系统提示词（Identity + Instructions）
- ``build_agent``：根据模型配置创建 Agent（含 checkpointer 短期记忆）
- ``stream_agent``：以 stream_mode="messages" 流式生成回复

数据流：
    用户消息 → build_human_message → agent.stream(stream_mode="messages")
    → Checkpointer 自动读写历史 → LLM 逐 token 返回 → SSE yield 给前端
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from loguru import logger

from app.config import get_settings

settings = get_settings()

# ========== 系统提示词（四段式：Identity + Instructions + Examples + Context） ==========
SYSTEM_PROMPT = """你是「AI 学习助手」，一位个性化的学习陪伴 Agent。

【身份 Identity】
你陪伴用户学习各类技术知识，目标是帮用户真正「掌握」每个知识点，而不只是记住名词。

【指令 Instructions】
1. 回答用户问题时，先用一句通俗的话说清概念是干什么的，再展开细节
2. 涉及代码或数据结构时，给出最小可识别的例子
3. 涉及流程时，画出 mermaid 流程图
4. 每讲完一个小节，输出一个思维导图（mermaid mindmap）
5. 如果用户说的不对，明确指出错误并给出正确答案
6. 不知道就说不知道，不要编造

【上下文 Context】
当前是 Day 2 阶段，Agent 骨架刚搭好，还没有接知识库（kb_facts/kb_style/kb_thinking），
所以暂时按通用学习助手回答，不要假装能查询用户的长期知识库。
注意：你可以正常读取当前会话的短期记忆（thread_id 隔离的对话历史）。
"""


# ========== 全局 Checkpointer（短期记忆，存 SQLite） ==========
# 单例：整个进程共享一个 SQLite 连接 + SqliteSaver
_DB_PATH = Path("./data/chat.db")
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
_CHECKPOINTER = SqliteSaver(_CONN)
_CHECKPOINTER.setup()  # 自动建 checkpoints 表
logger.info(f"Checkpointer 已初始化：{_DB_PATH.absolute()}")


# ========== Agent 工厂 ==========
def build_agent(
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """根据模型配置创建学习助手 Agent。

    Args:
        model_name: 模型名（如 deepseek-chat），默认读 settings.llm_model_name
        base_url: 模型服务端点，默认读 settings.llm_base_url
        api_key: 模型 API Key，默认读 settings.llm_api_key

    Returns:
        ChatAgentExecutor：已编译的 LangGraph 图，可 invoke / stream

    Note:
        - 项目支持用户自选模型（对应 DeepTutor 的工厂模式）
        - 当前用 OpenAI 兼容协议接 DeepSeek；后续可扩展其他 provider
        - checkpointer 已全局初始化，这里直接复用
    """
    _model_name = model_name or settings.llm_model_name
    _base_url = base_url or settings.llm_base_url
    _api_key = api_key or settings.llm_api_key

    if not _api_key:
        raise ValueError(
            "LLM_API_KEY 未配置，无法创建 Agent。请在 backend/.env 中填入 DeepSeek API Key。"
        )

    logger.info(f"正在创建 Agent：model={_model_name}, base_url={_base_url}")

    # 用 init_chat_model 屏蔽各家 SDK 差异（Day 1 学过）
    model = init_chat_model(
        model=_model_name,
        model_provider="openai",  # DeepSeek 兼容 OpenAI 协议
        base_url=_base_url,
        api_key=_api_key,
    )

    # create_agent 是 LangGraph 语法糖，打包 model + prompt + checkpointer
    # Day 2 阶段先不接工具（tools=[]），Day 4 会接 RAG 检索工具
    agent = create_agent(
        model=model,
        tools=[],  # 占位：Day 4 接 RAG 工具，Day 5 接知识库工具
        system_prompt=SYSTEM_PROMPT,
        checkpointer=_CHECKPOINTER,
    )
    logger.info("Agent 创建成功")
    return agent


# ========== 全局 Agent 单例（开发期用默认模型配置） ==========
# 生产应该按用户选的模型动态创建；Day 2 先用单例跑通
_AGENT: Any | None = None


def get_agent() -> Any:
    """获取全局 Agent 单例。

    首次调用时按 .env 默认配置创建，后续复用。
    """
    global _AGENT
    if _AGENT is None:
        _AGENT = build_agent()
    return _AGENT


# ========== 流式生成 ==========
def stream_agent(
    user_message: str,
    thread_id: str,
) -> Generator[str, None, None]:
    """把用户消息交给 Agent，SSE 逐 chunk yield 文本片段。

    Args:
        user_message: 用户输入的文本
        thread_id: 会话唯一标识（短期记忆隔离维度）

    Yields:
        str: LLM 返回的 token 片段（AIMessageChunk.content）

    数据流：
        1. 包装 HumanMessage
        2. agent.stream(stream_mode="messages") 启动流式
        3. Checkpointer 自动读历史 messages（首次为空）
        4. LLM 逐 token 返回 AIMessageChunk
        5. 每个 chunk 的 content yield 给前端
        6. 流结束后 Checkpointer 自动存新 messages

    Note:
        - stream_mode="messages" 是 token 级粒度，适合 SSE
        - stream_mode="updates" 是节点级粒度，粒度粗不适合聊天
        - thread_id 由前端生成并存储（Web 用 localStorage）
    """
    agent = get_agent()

    # 构造输入：messages 列表只放用户这一条新消息
    # 历史消息由 Checkpointer 按 thread_id 自动加载，不用手动拼
    input_messages: list[BaseMessage] = [HumanMessage(content=user_message)]
    config = {"configurable": {"thread_id": thread_id}}

    logger.info(f"stream_agent 启动：thread_id={thread_id}, msg_len={len(user_message)}")

    # stream_mode="messages" 返回 (chunk, metadata) 元组
    for chunk, metadata in agent.stream(
        {"messages": input_messages},
        config,
        stream_mode="messages",
    ):
        # chunk 是 AIMessageChunk，content 是 token 片段
        # metadata 标明来自哪个 node、哪个 langgraph_step（调试用）
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            yield chunk.content
