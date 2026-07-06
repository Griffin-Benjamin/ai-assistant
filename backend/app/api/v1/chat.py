"""对话路由：SSE 流式接口 + 会话管理（Day 4：异步改造 + 会话管理）。

提供：
- POST /stream   异步 SSE 流式对话（Day 4 改造为异步）
- GET  /history  查询会话历史（Day 4 新增）
- DELETE /{thread_id}  清空会话（Day 4 新增）

Day 4 改造点：
    - chat_stream 同步 → async def
    - stream_agent → astream_agent（异步生成器）
    - 新增 /history 和 DELETE /{thread_id} 会话管理接口

SSE 协议落地形态：
    响应头 Content-Type: text/event-stream
    每条消息格式：data: <内容>\\n\\n
    浏览器用 ReadableStream 逐 chunk 读取
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.learning_agent import (
    astream_agent,
    clear_chat_session,
    get_chat_history,
)
from app.common.logger import get_logger

logger = get_logger()
router = APIRouter()


# ========== 请求 / 响应模型 ==========
class ChatStreamRequest(BaseModel):
    """SSE 对话请求体。

    Attributes:
        message: 用户输入的文本
        thread_id: 会话唯一标识，前端生成并存储（Web 用 localStorage）
                  同一个 thread_id 的多次调用会共享短期记忆
    """

    message: str = Field(..., min_length=1, description="用户输入的文本")
    thread_id: str = Field(
        default="default-session",
        description="会话唯一标识，用于短期记忆隔离",
    )


class ChatStreamEvent(BaseModel):
    """SSE 事件的数据部分（仅用于 OpenAPI 文档展示，实际返回纯文本）。"""

    type: str = Field(..., description="事件类型：token / done / error")
    content: str = Field(..., description="事件内容")


class ChatHistoryMessage(BaseModel):
    """历史消息项。"""

    role: str = Field(..., description="消息角色：human/ai/system/tool")
    content: str = Field(..., description="消息内容")
    type: str = Field(..., description="消息类型名：HumanMessage/AIMessage/...")


class ChatHistoryResponse(BaseModel):
    """会话历史响应。"""

    thread_id: str
    messages: list[ChatHistoryMessage]
    count: int


class ChatClearResponse(BaseModel):
    """清空会话响应。"""

    thread_id: str
    success: bool
    message: str


# ========== SSE 流式对话接口（Day 4：异步） ==========
@router.post("/stream")
async def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """异步 SSE 流式对话接口。

    数据流：
        前端 POST {message, thread_id}
          → astream_agent(user_message, thread_id)  # 异步生成器
            → agent.astream(stream_mode="messages") # 异步流式
              → AsyncCheckpointer 自动读历史
              → LLM 逐 token 返回
          → 包装成 SSE event: data: {type:token, content:...}\\n\\n
          → 前端 ReadableStream 逐 chunk 渲染

    Args:
        req: ChatStreamRequest，含 message 和 thread_id

    Returns:
        EventSourceResponse: SSE 流式响应

    Note:
        - Day 4 起改为 async def，配合 AsyncSqliteSaver
        - EventSourceResponse 接受异步生成器作为参数
    """
    logger.info(f"POST /chat/stream：thread_id={req.thread_id}, msg={req.message[:50]}...")

    async def event_generator():
        """异步 SSE 事件生成器。"""
        try:
            # type=token: 逐 token 流式输出
            async for token in astream_agent(req.message, req.thread_id):
                yield {"event": "token", "data": token}

            # type=done: 流结束信号
            yield {"event": "done", "data": "[DONE]"}
        except ValueError as e:
            # 配置错误（如 LLM_API_KEY 未填）
            logger.error(f"chat_stream 配置错误：{e}")
            yield {"event": "error", "data": f"配置错误：{e}"}
        except Exception as e:
            # 其他运行时错误
            logger.exception(f"chat_stream 运行时错误：{e}")
            yield {"event": "error", "data": f"内部错误：{e}"}

    return EventSourceResponse(event_generator())


# ========== 会话历史查询（Day 4 新增） ==========
@router.get("/history", response_model=ChatHistoryResponse)
async def chat_history(
    thread_id: str = Query(..., description="会话唯一标识"),
) -> ChatHistoryResponse:
    """查询指定会话的历史消息（从 AsyncCheckpointer 读取）。

    Args:
        thread_id: 会话唯一标识

    Returns:
        ChatHistoryResponse: 含消息列表
    """
    logger.info(f"GET /chat/history：thread_id={thread_id}")
    try:
        messages = await get_chat_history(thread_id)
        return ChatHistoryResponse(
            thread_id=thread_id,
            messages=[ChatHistoryMessage(**m) for m in messages],
            count=len(messages),
        )
    except RuntimeError as e:
        # AgentManager 未初始化
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception(f"查询历史失败：{e}")
        raise HTTPException(status_code=500, detail=f"查询历史失败：{e}")


# ========== 清空会话（Day 4 新增） ==========
@router.delete("/{thread_id}", response_model=ChatClearResponse)
async def clear_session(thread_id: str) -> ChatClearResponse:
    """清空指定会话的短期记忆（从 AsyncCheckpointer 删除）。

    Args:
        thread_id: 会话唯一标识

    Returns:
        ChatClearResponse: 含删除结果
    """
    logger.info(f"DELETE /chat/{thread_id}")
    try:
        success = await clear_chat_session(thread_id)
        return ChatClearResponse(
            thread_id=thread_id,
            success=success,
            message="会话已清空" if success else "清空失败（会话可能不存在）",
        )
    except Exception as e:
        logger.exception(f"清空会话失败：{e}")
        return ChatClearResponse(
            thread_id=thread_id,
            success=False,
            message=f"清空失败：{e}",
        )
