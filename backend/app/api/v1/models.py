"""模型配置路由占位。

后续 Task 将在此实现：
- POST   /          创建/更新模型配置
- GET    /          列出用户已配置的模型
- GET    /matrix    获取模型能力矩阵
- DELETE /{id}      删除模型配置
"""
from fastapi import APIRouter

# 占位空路由；该路由暂未注册到 main.py，保留以便后续启用
router = APIRouter()
