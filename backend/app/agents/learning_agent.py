"""学习助手 Agent 占位模块。

后续 Task 将在此实现：
- SYSTEM_PROMPT：定义学习助手角色与风格化回复规则
- style_injector：从 kb_style 库抽取用户风格样本注入 prompt 的 Middleware
- stream_agent：把用户消息交给 Agent，SSE 逐 chunk 返回
- build_agent：根据用户选择的模型配置初始化 Agent

当前仅提供占位，避免后续导入失败。
"""
