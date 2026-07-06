"""AI 学习助手核心工作流（Day 7：LangGraph StateGraph）。

用 StateGraph 编排项目核心 5 步链路：
    1. chat            —— 对话学习（接收用户消息）
    2. extract_style   —— 风格抽取（每 5 轮批量抽取，写入 kb_style）
    3. summarize       —— 知识汇总（每 N 轮或会话结束，写入 kb_facts）
    4. update_kb       —— 三库更新 + 精简化（置信度衰减）
    5. style_reply     —— 风格化回复（三库检索 + 注入 + 回复）

LangGraph 三要素：
    - State：共享状态（TypedDict + Annotated reducer）
    - Node：节点函数（接收 State，返回部分 State 更新）
    - Edge：边（普通边 + 条件边 + Command）

本项目用到的 Workflow 模式：
    - Prompt Chaining：chat → extract_style → style_reply（线性）
    - Routing：根据消息轮数路由（<5 轮直接回复 / >=5 轮触发抽取）
    - Conditional Edge：用 add_conditional_edges 实现 Routing

State 设计（5 字段 + 2 reducer）：
    - messages：对话历史（operator.add 追加式）
    - turn_count：当前轮数（覆盖式）
    - user_id：用户 ID（不可变）
    - extracted_styles：抽取的风格样本（operator.add 追加式）
    - final_reply：最终回复（覆盖式，终止信号）
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

from app.services.kb_manager import kb_manager


# ========== State 定义 ==========
class LearningState(TypedDict):
    """学习助手工作流共享状态。

    字段更新策略（reducer）：
        - 默认覆盖：新值直接替换旧值
        - operator.add：追加式（list 用，避免覆盖丢失历史）

    选择策略的原则：
        - 累积型数据（messages、extracted_styles）用 operator.add
        - 当前态数据（turn_count、user_id、final_reply）用默认覆盖
    """
    # 累积型：每轮追加，不覆盖
    messages: Annotated[list, operator.add]

    # 当前态：覆盖式
    turn_count: int            # 当前对话轮数
    user_id: str               # 用户 ID（隔离维度）

    # 累积型：每次抽取追加
    extracted_styles: Annotated[list[str], operator.add]

    # 终止信号：最终回复
    final_reply: str


# ========== 节点函数 ==========
def chat_node(state: LearningState) -> dict:
    """节点 1：对话学习。

    职责：
        - 接收用户消息（已在 state.messages 中）
        - 简单生成一个回声回复（演示用，Day 8 接真实 Agent）
        - 更新 turn_count

    输入：state.messages（含最新用户消息）
    输出：{messages: [AI 回声], turn_count: +1}
    """
    user_msg = state["messages"][-1].content if state["messages"] else ""
    turn_count = state.get("turn_count", 0) + 1
    user_id = state.get("user_id", "default-user")

    logger.info(f"[chat_node] 第 {turn_count} 轮对话，user={user_id}，msg='{user_msg[:30]}...'")

    # Day 7 演示用：生成简单回声（Day 8 接真实 astream_agent）
    ai_reply = AIMessage(content=f"[chat_node 回声] 收到你的消息：{user_msg}")

    return {
        "messages": [ai_reply],
        "turn_count": turn_count,
    }


def extract_style_node(state: LearningState) -> dict:
    """节点 2：风格抽取（每 5 轮触发）。

    职责：
        - 从最近 5 轮对话中抽取用户语言风格样本
        - 写入 kb_style（ChromaDB）
        - 返回抽取出的样本列表（追加到 extracted_styles）

    触发条件：turn_count % 5 == 0（在 routing_edge 中判断）
    """
    turn_count = state.get("turn_count", 0)
    user_id = state.get("user_id", "default-user")

    logger.info(f"[extract_style_node] 第 {turn_count} 轮触发风格抽取")

    # Day 7 演示用：模拟抽取（Day 8 接真实 LLM with_structured_output）
    # 真实实现：取最近 5 轮对话 → 调 LLM 抽取风格 → 写入 kb_style
    mock_samples = [
        Document(
            page_content=f"第 {turn_count} 轮抽取：用户喜欢用类比（mock）",
            metadata={"user_id": user_id, "confidence": 0.85, "turn": turn_count},
        ),
    ]

    # 写入 kb_style
    try:
        kb_manager.add_style_samples(mock_samples)
        logger.info(f"[extract_style_node] 写入 kb_style {len(mock_samples)} 条")
    except Exception as e:
        logger.error(f"[extract_style_node] 写入失败：{e}")

    return {
        "extracted_styles": [s.page_content for s in mock_samples],
    }


def summarize_node(state: LearningState) -> dict:
    """节点 3：知识汇总（每 10 轮触发）。

    职责：
        - 从最近 10 轮对话中提取客观知识点（错题/笔记/心得）
        - 写入 kb_facts（ChromaDB）

    触发条件：turn_count % 10 == 0（在 routing_edge 中判断）
    """
    turn_count = state.get("turn_count", 0)
    user_id = state.get("user_id", "default-user")

    logger.info(f"[summarize_node] 第 {turn_count} 轮触发知识汇总")

    # Day 7 演示用：模拟汇总
    mock_facts = [
        Document(
            page_content=f"第 {turn_count} 轮汇总：用户学习了某个知识点（mock）",
            metadata={
                "user_id": user_id,
                "subject": "general",
                "source": "auto_summarize",
                "turn": turn_count,
            },
        ),
    ]

    try:
        kb_manager.add_facts(mock_facts)
        logger.info(f"[summarize_node] 写入 kb_facts {len(mock_facts)} 条")
    except Exception as e:
        logger.error(f"[summarize_node] 写入失败：{e}")

    return {}  # 不更新 state，只写库


def style_reply_node(state: LearningState) -> dict:
    """节点 4：风格化回复。

    职责：
        - 从 kb_style 检索用户风格样本
        - 拼到回复中（演示用，Day 8 接 style_injector middleware）
        - 设置 final_reply（终止信号）
    """
    user_id = state.get("user_id", "default-user")
    last_ai_msg = state["messages"][-1].content if state["messages"] else ""

    logger.info(f"[style_reply_node] 生成风格化回复")

    # 从 kb_style 检索样本
    try:
        style_docs = kb_manager.search_style(
            query="用户风格样本",
            k=2,
            filter={"user_id": user_id},
        )
        style_text = "\n".join(f"- {d.page_content}" for d in style_docs)
    except Exception as e:
        logger.warning(f"[style_reply_node] 检索风格失败：{e}")
        style_text = "（无风格样本）"

    final_reply = f"""{last_ai_msg}

【注入风格样本】
{style_text}
"""

    return {"final_reply": final_reply}


# ========== 条件边路由 ==========
def route_after_chat(state: LearningState) -> str:
    """条件边：chat 之后路由到哪个节点。

    路由逻辑：
        - turn_count % 10 == 0：先 summarize，再 extract_style，再 style_reply
        - turn_count % 5 == 0：先 extract_style，再 style_reply
        - 其他：直接 style_reply

    简化版：只返回下一个节点名，由 LangGraph 自动走下一步
    完整版：用 Command(goto=...) 实现多步跳转（Day 8 升级）
    """
    turn_count = state.get("turn_count", 0)

    if turn_count % 10 == 0:
        logger.debug(f"[route] turn={turn_count} → summarize")
        return "summarize"
    elif turn_count % 5 == 0:
        logger.debug(f"[route] turn={turn_count} → extract_style")
        return "extract_style"
    else:
        logger.debug(f"[route] turn={turn_count} → style_reply")
        return "style_reply"


def route_after_summarize(state: LearningState) -> str:
    """条件边：summarize 之后路由到 extract_style（继续抽取）。"""
    return "extract_style"


def route_after_extract(state: LearningState) -> str:
    """条件边：extract_style 之后路由到 style_reply。"""
    return "style_reply"


# ========== 构建工作流 ==========
def build_learning_workflow() -> Any:
    """构建学习助手核心工作流 StateGraph。

    工作流拓扑：
        START → chat → route_after_chat
                            ├─ summarize → extract_style → style_reply → END
                            ├─ extract_style → style_reply → END
                            └─ style_reply → END

    Returns:
        CompiledGraph: 编译后的可执行图

    Example:
        >>> graph = build_learning_workflow()
        >>> result = graph.invoke({
        ...     "messages": [HumanMessage(content="什么是装饰器")],
        ...     "turn_count": 0,
        ...     "user_id": "default-user",
        ...     "extracted_styles": [],
        ...     "final_reply": "",
        ... })
    """
    # 1. 创建 StateGraph
    workflow = StateGraph(LearningState)

    # 2. 添加节点
    workflow.add_node("chat", chat_node)
    workflow.add_node("extract_style", extract_style_node)
    workflow.add_node("summarize", summarize_node)
    workflow.add_node("style_reply", style_reply_node)

    # 3. 添加边
    # START → chat
    workflow.add_edge(START, "chat")

    # chat → 条件路由（summarize / extract_style / style_reply）
    workflow.add_conditional_edges(
        "chat",
        route_after_chat,
        {
            "summarize": "summarize",
            "extract_style": "extract_style",
            "style_reply": "style_reply",
        },
    )

    # summarize → extract_style（汇总完继续抽取）
    workflow.add_conditional_edges(
        "summarize",
        route_after_summarize,
        {"extract_style": "extract_style"},
    )

    # extract_style → style_reply
    workflow.add_conditional_edges(
        "extract_style",
        route_after_extract,
        {"style_reply": "style_reply"},
    )

    # style_reply → END
    workflow.add_edge("style_reply", END)

    # 4. 编译
    graph = workflow.compile()
    logger.info("Learning workflow 已编译：START → chat → route → ... → END")
    return graph


# ========== 运行工作流 ==========
def run_workflow(user_message: str, turn_count: int = 0, user_id: str = "default-user") -> dict:
    """运行学习助手工作流（同步，演示用）。

    Args:
        user_message: 用户消息
        turn_count: 当前轮数（外部传入，模拟多轮）
        user_id: 用户 ID

    Returns:
        dict: 最终 state（含 final_reply）
    """
    graph = build_learning_workflow()

    initial_state: LearningState = {
        "messages": [HumanMessage(content=user_message)],
        "turn_count": turn_count,
        "user_id": user_id,
        "extracted_styles": [],
        "final_reply": "",
    }

    result = graph.invoke(initial_state)
    logger.info(f"工作流执行完成，final_reply 长度 {len(result.get('final_reply', ''))}")
    return result
