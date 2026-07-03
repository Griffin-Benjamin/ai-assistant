"""对话路由占位。

后续 Task 将在此实现：
- POST /stream  SSE 流式对话接口
- GET  /history 查询会话历史
- DELETE /{thread_id} 清空会话
"""
from fastapi import APIRouter

# 占位空路由；该路由暂未注册到 main.py，保留以便后续启用
router = APIRouter()
