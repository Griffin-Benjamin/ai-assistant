"""人格路由占位。

Task 3 将在此实现完整的 RESTful 接口：
- POST   /          创建人格
- GET    /          列出人格（含预设）
- GET    /presets   列出预设人格
- GET    /{id}      查询人格
- PUT    /{id}      更新人格
- DELETE /{id}      删除人格
"""
from fastapi import APIRouter

# 占位空路由，确保 main.py import 不报错；具体接口后续实现
router = APIRouter()
