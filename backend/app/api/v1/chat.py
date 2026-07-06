"""对话路由：SSE 流式接口。

提供：
- POST /stream   SSE 流式对话（核心接口，Day 2 交付物）
- GET  /history  查询会话历史（Day 4 实现）
- DELETE /{thread_id}  清空会话（Day 4 实现）

SSE 协议落地形态：
    响应头 Content-Type: text/event-stream
    每条消息格式：data: <内容>\\n\\n
    浏览器用 ReadableStream 逐 chunk 读取
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agents.learning_agent import stream_agent
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


# ========== SSE 流式对话接口 ==========
@router.post("/stream")
def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """SSE 流式对话接口。

    数据流：
        前端 POST {message, thread_id}
          → stream_agent(user_message, thread_id)
            → agent.stream(stream_mode="messages")
              → Checkpointer 自动读历史
              → LLM 逐 token 返回
          → 包装成 SSE event: data: {type:token, content:...}\\n\\n
          → 前端 ReadableStream 逐 chunk 渲染

    Args:
        req: ChatStreamRequest，含 message 和 thread_id

    Returns:
        EventSourceResponse: SSE 流式响应

    Note:
        - thread_id 由前端生成（如 uuid4），存 localStorage
        - 同一个 thread_id 多次调用 = 多轮对话（短期记忆）
        - 不同 thread_id = 不同会话（互不影响）
    """
    logger.info(f"POST /chat/stream：thread_id={req.thread_id}, msg={req.message[:50]}...")

    def event_generator():
        """SSE 事件生成器。

        yield 格式由 sse-starlette 包装：
            yield {{"data": "..."}} → "data: ...\\n\\n"
        """
        try:
            # type=token: 逐 token 流式输出
            for token in stream_agent(req.message, req.thread_id):
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
