"""学习助手 Agent 核心模块。

提供：
- ``SYSTEM_PROMPT``：学习助手系统提示词（Identity + Instructions）
- ``style_injector``：风格注入 Middleware（wrap_model_call），从 Store 读样本拼到 system_prompt
- ``build_agent``：根据模型配置创建 Agent（含 checkpointer 短期记忆 + store 长期记忆 + middleware）
- ``stream_agent``：以 stream_mode="messages" 流式生成回复
- ``seed_mock_style``：向 Store 注入 mock 风格样本（开发期演示用，Day 5 接真实抽取）

数据流：
    用户消息 → agent.stream(stream_mode="messages")
    → style_injector 拦截模型调用：runtime.store 读样本 → override system_prompt
    → Checkpointer 自动读写历史 → LLM 逐 token 返回 → SSE yield 给前端
"""
from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.memory import InMemoryStore
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
当前是 Day 3 阶段，已接入风格注入 Middleware（从 Store 读用户风格样本拼到 system_prompt）。
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


# ========== 全局 Store（长期记忆，开发期用 InMemoryStore） ==========
# Day 3：开发期用内存 Store 跑通流程；Day 5+ 切换到 ChromaDB（接口兼容）
# namespace 约定：(scope, user_id)
#   - ("style", <user_id>)：用户风格样本
#   - ("facts", <user_id>)：用户事实画像（Day 5）
#   - ("thinking", <user_id>)：用户思维模式（Day 6）
_STORE = InMemoryStore()
logger.info("Store 已初始化：InMemoryStore（开发期，重启即丢；Day 5 切 ChromaDB）")


# ========== 风格注入 Middleware（wrap-style） ==========
# Day 3 理论讲的是 node-style 改 state['messages'][0]，实测 langgraph 1.x API 后修正：
# system_prompt 不在 state 里，而在 ModelRequest 里单独管，所以必须用 wrap_model_call。
# 这是 wrap-style：拦截模型调用 → 改 request → 调 handler 继续
_DEFAULT_USER_ID = "default-user"  # Day 5 接入认证后从 runtime.context.user_id 拿


@wrap_model_call
def style_injector(request, handler):
    """风格注入中间件：每次 LLM 调用前，从 Store 读用户风格样本，拼到 system_prompt。

    工作流程：
        1. 从 request.runtime.store 拿 Store 对象
        2. 按 namespace=("style", user_id) 检索风格样本
        3. 有样本：拼到原 system_prompt 后，用 request.override 生成新 request
        4. 无样本：原样放行
        5. 调 handler(new_request) 让真实模型调用继续

    Note:
        - 这是 wrap-style middleware（有 handler/call_next，控制流程）
        - 对比 node-style（before_model）：只改 state，碰不到 system_prompt
        - Store 检索是同步的；InMemoryStore.search 按 query 做简单匹配，ChromaDB 做语义检索
    """
    store = request.runtime.store
    namespace = ("style", _DEFAULT_USER_ID)

    try:
        items = store.search(namespace, query="风格样本", limit=3)
    except Exception as e:
        logger.warning(f"Store 检索失败，跳过风格注入：{e}")
        items = []

    if not items:
        logger.debug("无风格样本，原样放行")
        return handler(request)

    # 拼风格样本到 system_prompt 末尾
    style_lines = []
    for item in items:
        text = item.value.get("text") if isinstance(item.value, dict) else str(item.value)
        if text:
            style_lines.append(f"- {text}")
    style_block = "\n".join(style_lines)

    new_prompt = f"{request.system_prompt}\n\n【用户风格样本（请尽量贴合此风格回答）】\n{style_block}"
    new_request = request.override(system_prompt=new_prompt)

    logger.info(f"风格注入成功：拼入 {len(items)} 条样本，prompt 长度 "
                f"{len(request.system_prompt)} → {len(new_prompt)}")

    return handler(new_request)


# ========== mock 风格样本（开发期演示用） ==========
def seed_mock_style(user_id: str = _DEFAULT_USER_ID) -> None:
    """向 Store 注入 mock 风格样本，用于 Day 3 演示风格注入效果。

    Day 5 会接入真实抽取：每 5 轮对话批量调 LLM 抽取风格 → put 到 Store。
    """
    namespace = ("style", user_id)
    samples = [
        ("style-1", "回答时多用类比，把抽象概念类比到生活中的事物"),
        ("style-2", "每讲完一个点就出 1-2 道自检题，验证用户是否真的懂了"),
        ("style-3", "语气轻松，像朋友聊天，不要用'您'，用'你'"),
    ]
    for key, text in samples:
        _STORE.put(namespace, key, {"text": text})
    logger.info(f"已注入 {len(samples)} 条 mock 风格样本：namespace={namespace}")


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
        CompiledStateGraph：已编译的 LangGraph 图，可 invoke / stream

    Note:
        - 项目支持用户自选模型（对应 DeepTutor 的工厂模式）
        - 当前用 OpenAI 兼容协议接 DeepSeek；后续可扩展其他 provider
        - checkpointer + store 已全局初始化，这里直接复用
        - middleware=[style_injector]：每次 LLM 调用前注入用户风格
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

    # create_agent 是 LangGraph 语法糖，打包 model + prompt + checkpointer + store + middleware
    # Day 2 阶段先不接工具（tools=[]），Day 4 会接 RAG 检索工具
    agent = create_agent(
        model=model,
        tools=[],  # 占位：Day 4 接 RAG 工具，Day 5 接知识库工具
        system_prompt=SYSTEM_PROMPT,
        checkpointer=_CHECKPOINTER,
        store=_STORE,
        middleware=[style_injector],
    )
    logger.info("Agent 创建成功（含 style_injector middleware）")
    return agent


# ========== 全局 Agent 单例（开发期用默认模型配置） ==========
# 生产应该按用户选的模型动态创建；Day 3 先用单例跑通
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
        3. style_injector 拦截模型调用，从 Store 读样本拼到 system_prompt
        4. Checkpointer 自动读历史 messages（首次为空）
        5. LLM 逐 token 返回 AIMessageChunk
        6. 每个 chunk 的 content yield 给前端
        7. 流结束后 Checkpointer 自动存新 messages

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
