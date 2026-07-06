"""学习助手 Agent 核心模块（Day 4：异步 Checkpointer 改造）。

提供：
- ``SYSTEM_PROMPT``：学习助手系统提示词（Identity + Instructions）
- ``style_injector``：风格注入 Middleware（wrap_model_call），从 Store 读样本拼到 system_prompt
- ``AgentManager``：异步 Agent 管理器（封装 AsyncSqliteSaver 生命周期）
- ``astream_agent``：以 stream_mode="messages" 异步流式生成回复
- ``seed_mock_style``：向 Store 注入 mock 风格样本

Day 4 改造点（相对 Day 3）：
1. 同步 SqliteSaver → 异步 AsyncSqliteSaver（aiosqlite）
2. 模块级全局变量 → AgentManager 类封装（配合 FastAPI lifespan）
3. 同步 stream_agent → 异步 astream_agent（async generator）
4. agent.stream → agent.astream（异步流式）

数据流：
    用户消息 → agent.astream(stream_mode="messages")
    → style_injector 拦截模型调用：runtime.store 读样本 → override system_prompt
    → AsyncCheckpointer 自动读写历史 → LLM 逐 token 返回 → SSE yield 给前端
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import aiosqlite
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
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
当前是 Day 4 阶段，Checkpointer 已升级为异步（AsyncSqliteSaver），SSE 接口改为异步流式。
注意：你可以正常读取当前会话的短期记忆（thread_id 隔离的对话历史）。
"""


# ========== 全局 Store（长期记忆，开发期用 InMemoryStore） ==========
# Store 是线程安全的同步对象，异步 Agent 也能用（内部 IO 极少）
# Day 5 切换到 ChromaDB（接口兼容）
# namespace 约定：(scope, user_id)
#   - ("style", <user_id>)：用户风格样本
#   - ("facts", <user_id>)：用户事实画像（Day 5）
#   - ("thinking", <user_id>)：用户思维模式（Day 6）
_STORE = InMemoryStore()
logger.info("Store 已初始化：InMemoryStore（开发期，重启即丢；Day 5 切 ChromaDB）")


# ========== 风格注入 Middleware（wrap-style） ==========
# Day 3 实测 langgraph 1.x API 后确认：
# system_prompt 不在 state 里，而在 ModelRequest 里单独管，所以必须用 wrap_model_call。
_DEFAULT_USER_ID = "default-user"  # Day 5 接入认证后从 runtime.context.user_id 拿


@wrap_model_call
async def style_injector(request, handler):
    """风格注入中间件：每次 LLM 调用前，从 Store 读用户风格样本，拼到 system_prompt。

    工作流程：
        1. 从 request.runtime.store 拿 Store 对象
        2. 按 namespace=("style", user_id) 检索风格样本
        3. 有样本：拼到原 system_prompt 后，用 request.override 生成新 request
        4. 无样本：原样放行
        5. await handler(new_request) 让真实模型调用继续

    Note:
        - 这是 wrap-style middleware（有 handler/call_next，控制流程）
        - Day 4 改造：同步 def → async def，配合异步 Agent（astream）
        - 异步 Agent 要求 middleware 也必须 async，否则报 NotImplementedError
        - Store 检索是同步的（InMemoryStore.search），但 handler 必须 await
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
        return await handler(request)

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

    return await handler(new_request)


# ========== mock 风格样本（开发期演示用） ==========
def seed_mock_style(user_id: str = _DEFAULT_USER_ID) -> None:
    """向 Store 注入 mock 风格样本，用于演示风格注入效果。

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
            tools=[],  # Day 6 接 RAG 检索工具
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
