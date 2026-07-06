"""学习助手 Agent 核心模块（Day 6：Agentic RAG）。

提供：
- ``SYSTEM_PROMPT``：学习助手系统提示词（Identity + Instructions）
- ``style_injector``：风格注入 Middleware（wrap_model_call），从 kb_style（ChromaDB）读样本
- ``AgentManager``：异步 Agent 管理器（封装 AsyncSqliteSaver 生命周期）
- ``astream_agent``：以 stream_mode="messages" 异步流式生成回复
- ``seed_mock_style``：向 kb_style（ChromaDB）注入 mock 风格样本

Day 6 改造点（相对 Day 5）：
1. Agent 接入 RAG 工具：tools=[search_knowledge_base]（Agentic RAG）
2. SYSTEM_PROMPT 增加 RAG 工具使用指引：何时调工具、何时直接回答
3. astream_agent 改 stream_mode=["messages", "updates"]，让前端看到工具调用过程

数据流：
    用户消息 → agent.astream(stream_mode=["messages", "updates"])
    → style_injector 拦截模型调用：kb_manager.search_style 语义检索样本 → override system_prompt
    → LLM 决定是否调 search_knowledge_base 工具
    → 调工具：从 kb_facts 检索 → ToolMessage 返回结果
    → LLM 看结果生成最终回答（或再调一次工具换 query）
    → AsyncCheckpointer 自动读写历史 → SSE yield 给前端
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import aiosqlite
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore
from loguru import logger

from app.config import get_settings
from app.services.kb_manager import kb_manager
from app.tools.rag_tools import search_knowledge_base

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

【RAG 工具使用指引（Day 6）】
你有一个工具 `search_knowledge_base`，可以从用户个人知识库检索客观知识点（错题/笔记/心得）。

何时调用工具：
- 用户问之前学过的知识（如"我之前笔记里怎么写的装饰器"）
- 用户问的概念可能在已上传的学习资料中
- 用户明确要求"查一下我的笔记"

何时不调用工具（直接回答）：
- 闲聊（如"今天怎么样"）
- 通用知识（如"什么是 Python"）—— 直接用你内置知识回答
- 实时信息（如"现在几点"）—— 你没有这个能力，告诉用户

调用工具技巧：
- query 用用户问题的核心关键词，可以同义改写
- 如果第一次检索结果不够，可以换关键词再调一次
- 工具返回结果后，结合用户问题给出针对性回答，引用笔记内容时要标注"你的笔记里写到..."

【上下文 Context】
当前是 Day 6 阶段，Agentic RAG 已就绪（kb_facts 检索工具已挂载）。
三库分离架构：kb_facts（@tool 检索）/ kb_style（style_injector 注入）/ kb_thinking（Day 8 注入）。
注意：你可以正常读取当前会话的短期记忆（thread_id 隔离的对话历史）。
"""


# ========== 全局 Store（用于 runtime.store，开发期用 InMemoryStore） ==========
# Day 5 起风格样本改用 ChromaDB（kb_manager.style），不依赖 Store
# Store 保留用于其他场景：配置画像、会话级临时数据等
_STORE = InMemoryStore()
logger.info("Store 已初始化：InMemoryStore（用于 runtime.store 其他场景）")


# ========== 风格注入 Middleware（wrap-style） ==========
# Day 3 实测 langgraph 1.x API 后确认：
# system_prompt 不在 state 里，而在 ModelRequest 里单独管，所以必须用 wrap_model_call。
# Day 5 改造：从 ChromaDB（kb_style collection）做语义检索，不再用 Store
_DEFAULT_USER_ID = "default-user"  # Day 8 接入认证后从 runtime.context.user_id 拿


@wrap_model_call
async def style_injector(request, handler):
    """风格注入中间件：每次 LLM 调用前，从 kb_style（ChromaDB）读用户风格样本，拼到 system_prompt。

    工作流程：
        1. 用 kb_manager.search_style 语义检索风格样本（不是关键词精确匹配）
        2. 有样本：拼到原 system_prompt 后，用 request.override 生成新 request
        3. 无样本：原样放行
        4. await handler(new_request) 让真实模型调用继续

    Day 5 改造点（相对 Day 4）：
        - 数据源：InMemoryStore.search → kb_manager.search_style（ChromaDB）
        - 检索方式：精确匹配 → 语义检索（384 维向量相似度）
        - 持久化：重启即丢 → 持久化到 ./data/chroma/

    Note:
        - 这是 wrap-style middleware（有 handler/call_next，控制流程）
        - 异步 Agent 要求 middleware 也必须 async，否则报 NotImplementedError
        - kb_manager.search_style 是同步的（Chroma 同步 API），但 handler 必须 await
    """
    try:
        # 用用户最近消息做 query 做语义检索（更贴合当前话题）
        # 简化版：用固定 query；Day 8 可改成取最后一条 HumanMessage.content
        query = "用户风格样本"
        items = kb_manager.search_style(
            query=query,
            k=3,
            filter={"user_id": _DEFAULT_USER_ID},
        )
    except Exception as e:
        logger.warning(f"kb_style 检索失败，跳过风格注入：{e}")
        items = []

    if not items:
        logger.debug("无风格样本，原样放行")
        return await handler(request)

    # 拼风格样本到 system_prompt 末尾
    style_lines = [f"- {doc.page_content}" for doc in items if doc.page_content]
    style_block = "\n".join(style_lines)

    new_prompt = f"{request.system_prompt}\n\n【用户风格样本（请尽量贴合此风格回答）】\n{style_block}"
    new_request = request.override(system_prompt=new_prompt)

    logger.info(f"风格注入成功：拼入 {len(items)} 条样本（来自 kb_style ChromaDB），"
                f"prompt 长度 {len(request.system_prompt)} → {len(new_prompt)}")

    return await handler(new_request)


# ========== mock 风格样本（开发期演示用） ==========
def seed_mock_style(user_id: str = _DEFAULT_USER_ID) -> None:
    """向 kb_style（ChromaDB）注入 mock 风格样本，用于演示风格注入效果。

    Day 8 会接入真实抽取：每 5 轮对话批量调 LLM 抽取风格 → add_style_samples 到 ChromaDB。
    """
    samples = [
        Document(
            page_content="回答时多用类比，把抽象概念类比到生活中的事物",
            metadata={"user_id": user_id, "confidence": 0.9, "type": "phrase"},
        ),
        Document(
            page_content="每讲完一个点就出 1-2 道自检题，验证用户是否真的懂了",
            metadata={"user_id": user_id, "confidence": 0.85, "type": "habbit"},
        ),
        Document(
            page_content="语气轻松，像朋友聊天，不要用'您'，用'你'",
            metadata={"user_id": user_id, "confidence": 0.8, "type": "tone"},
        ),
    ]
    ids = kb_manager.add_style_samples(samples)
    logger.info(f"已注入 {len(ids)} 条 mock 风格样本到 kb_style（ChromaDB），user_id={user_id}")
    return ids


# ========== Agent 管理器（Day 4：异步 Checkpointer 封装） ==========
class AgentManager:
    """异步 Agent 管理器：封装 AsyncSqliteSaver 生命周期 + Agent 单例。

    Day 4 改造原因：
        - 同步 SqliteSaver 在模块顶层初始化（sqlite3.connect + SqliteSaver）
        - 异步 AsyncSqliteSaver 必须在异步环境中初始化（await aiosqlite.connect）
        - 因此不能在模块顶层初始化，必须封装成类 + 在 FastAPI lifespan 中 await init()

    生命周期：
        FastAPI 启动 → lifespan → await agent_manager.init()  → 创建连接 + Agent
        请求进来     → await astream_agent(...)                → 复用 Agent 单例
        FastAPI 关闭 → lifespan → await agent_manager.close() → 关闭连接
    """

    def __init__(self) -> None:
        self.conn: aiosqlite.Connection | None = None
        self.checkpointer: AsyncSqliteSaver | None = None
        self.agent: Any = None
        self._db_path = Path("./data/chat.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self, model_name: str | None = None,
                   base_url: str | None = None,
                   api_key: str | None = None) -> None:
        """初始化异步 Checkpointer + Agent（在 FastAPI lifespan 中调用）。

        Args:
            model_name: 模型名，默认读 settings.llm_model_name
            base_url: 模型服务端点，默认读 settings.llm_base_url
            api_key: 模型 API Key，默认读 settings.llm_api_key
        """
        logger.info(f"AgentManager 初始化中：db={self._db_path.absolute()}")

        # 1. 建立异步 SQLite 连接
        self.conn = await aiosqlite.connect(str(self._db_path))
        logger.info("aiosqlite 连接已建立")

        # 2. 实例化异步 Checkpointer + 自动建表
        self.checkpointer = AsyncSqliteSaver(conn=self.conn)
        await self.checkpointer.setup()  # 异步建 checkpoints 表
        logger.info("AsyncSqliteSaver 已初始化 + 表已就绪")

        # 3. 创建 Agent
        self.agent = await self._build_agent(model_name, base_url, api_key)
        logger.info("Agent 创建成功（含 style_injector middleware）")

    async def close(self) -> None:
        """关闭异步连接（在 FastAPI lifespan shutdown 中调用）。"""
        if self.conn is not None:
            await self.conn.close()
            logger.info("aiosqlite 连接已关闭")
        self.conn = None
        self.checkpointer = None
        self.agent = None

    async def _build_agent(self, model_name: str | None = None,
                           base_url: str | None = None,
                           api_key: str | None = None) -> Any:
        """根据模型配置创建学习助手 Agent（异步）。"""
        _model_name = model_name or settings.llm_model_name
        _base_url = base_url or settings.llm_base_url
        _api_key = api_key or settings.llm_api_key

        if not _api_key:
            raise ValueError(
                "LLM_API_KEY 未配置，无法创建 Agent。请在 backend/.env 中填入 DeepSeek API Key。"
            )

        logger.info(f"创建 Agent：model={_model_name}, base_url={_base_url}")

        model = init_chat_model(
            model=_model_name,
            model_provider="openai",  # DeepSeek 兼容 OpenAI 协议
            base_url=_base_url,
            api_key=_api_key,
        )

        agent = create_agent(
            model=model,
            tools=[search_knowledge_base],  # Day 6：Agentic RAG 检索工具
            system_prompt=SYSTEM_PROMPT,
            checkpointer=self.checkpointer,
            store=_STORE,
            middleware=[style_injector],
        )
        return agent

    def get_agent(self) -> Any:
        """获取已初始化的 Agent 单例（init 后调用）。"""
        if self.agent is None:
            raise RuntimeError("AgentManager 未初始化，请先 await agent_manager.init()")
        return self.agent


# ========== 全局 AgentManager 单例 ==========
agent_manager = AgentManager()


# ========== 异步流式生成 ==========
async def astream_agent(
    user_message: str,
    thread_id: str,
) -> AsyncGenerator[str, None]:
    """把用户消息交给 Agent，异步 SSE 逐 chunk yield 文本片段。

    Day 4 改造点：
        - 同步 stream_agent → 异步 astream_agent
        - agent.stream → agent.astream（异步流式）
        - yield from → async for + yield

    Args:
        user_message: 用户输入的文本
        thread_id: 会话唯一标识（短期记忆隔离维度）

    Yields:
        str: LLM 返回的 token 片段（AIMessageChunk.content）

    数据流：
        1. 包装 HumanMessage
        2. agent.astream(stream_mode="messages") 启动异步流式
        3. style_injector 拦截模型调用，从 Store 读样本拼到 system_prompt
        4. AsyncCheckpointer 自动读历史 messages（首次为空）
        5. LLM 逐 token 返回 AIMessageChunk
        6. 每个 chunk 的 content yield 给前端
        7. 流结束后 AsyncCheckpointer 自动存新 messages
    """
    agent = agent_manager.get_agent()

    input_messages: list[BaseMessage] = [HumanMessage(content=user_message)]
    config = {"configurable": {"thread_id": thread_id}}

    logger.info(f"astream_agent 启动：thread_id={thread_id}, msg_len={len(user_message)}")

    # astream 是异步流式，async for 逐 chunk 消费
    async for chunk, metadata in agent.astream(
        {"messages": input_messages},
        config,
        stream_mode="messages",
    ):
        if isinstance(chunk, AIMessageChunk) and chunk.content:
            yield chunk.content


# ========== 会话管理（Day 4 新增） ==========
async def get_chat_history(thread_id: str) -> list[dict]:
    """查询指定会话的历史消息（从 AsyncCheckpointer 读取）。

    Args:
        thread_id: 会话唯一标识

    Returns:
        list[dict]: 消息列表，每条含 role/content/type
    """
    agent = agent_manager.get_agent()
    config = {"configurable": {"thread_id": thread_id}}

    # agent.aget_state 返回当前 State 快照，含 messages 列表
    state = await agent.aget_state(config)

    messages: list[dict] = []
    if state and state.values and "messages" in state.values:
        for msg in state.values["messages"]:
            role = msg.type if hasattr(msg, "type") else "unknown"
            content = msg.content if hasattr(msg, "content") else str(msg)
            messages.append({
                "role": role,
                "content": content,
                "type": type(msg).__name__,
            })
    return messages


async def clear_chat_session(thread_id: str) -> bool:
    """清空指定会话的短期记忆（从 AsyncCheckpointer 删除）。

    Args:
        thread_id: 会话唯一标识

    Returns:
        bool: 是否删除成功
    """
    checkpointer = agent_manager.checkpointer
    if checkpointer is None:
        return False

    try:
        await checkpointer.adelete_thread(thread_id)
        logger.info(f"会话 {thread_id} 短期记忆已清空")
        return True
    except Exception as e:
        logger.error(f"清空会话 {thread_id} 失败：{e}")
        return False
