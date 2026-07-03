"""定时任务路由占位。

Task 3 将在此实现完整的 RESTful 接口：
- POST   /            创建任务
- GET    /            列出任务
- GET    /{id}        查询任务
- PUT    /{id}        更新任务
- DELETE /{id}        删除任务
- POST   /{id}/toggle 启用/停用任务
"""
from fastapi import APIRouter

# 占位空路由，确保 main.py import 不报错；具体接口后续实现
router = APIRouter()
