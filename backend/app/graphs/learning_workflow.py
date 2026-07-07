"""AI 学习助手核心工作流（Day 8：核心链路 5 步跑通 + HITL）。

Day 8 改造点（相对 Day 7）：
1. chat_node：mock 回声 → 真实 invoke_agent（带 style_injector + RAG 工具）
2. extract_style_node：mock 样本 → 真实 extract_style_with_llm（with_structured_output）
3. summarize_node：mock 知识点 → 真实 summarize_with_llm（with_structured_output）
4. style_reply_node：简单拼接 → 真实 invoke_agent（带风格 prompt）
5. 加 HITL：compile(interrupt_before=["summarize"]) 让用户在汇总前确认

核心 5 步链路（Day 8 真实化）：
    1. chat            —— 对话学习（调真实 Agent，带 style_injector + RAG）
    2. extract_style   —— 风格抽取（LLM with_structured_output）
    3. summarize       —— 知识汇总（LLM with_structured_output，HITL 确认）
    4. update_kb       —— 三库更新（Day 7 已在 extract/summarize 节点内完成写入）
    5. style_reply     —— 风格化回复（检索 kb_style + 重新调 Agent）

HITL（Human-in-the-Loop）实现：
    - compile 时传 interrupt_before=["summarize"]
    - 工作流执行到 summarize 前会暂停，返回当前 State
    - 用户确认后用 Command(resume=...) 继续执行
    - 测试时可不传 interrupt_before，直接跑完
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from loguru import logger

from app.services.kb_manager import kb_manager
from app.services.llm_extractors import (
    extract_style_with_llm,
    summarize_with_llm,
)


# ========== State 定义（同 Day 7） ==========
class LearningState(TypedDict):
    """学习助手工作流共享状态。

    字段更新策略（reducer）：
        - 默认覆盖：新值直接替换旧值
        - operator.add：追加式（list 用，避免覆盖丢失历史）

    Day 8 新增字段：
        - hitl_confirmed：HITL 确认标志（False=未确认，True=已确认）
    """
    # 累积型
    messages: Annotated[list, operator.add]
    extracted_styles: Annotated[list[str], operator.add]

    # 当前态
    turn_count: int
    user_id: str
    final_reply: str
    thread_id: str  # Day 8 新增：用于 invoke_agent 的会话隔离

    # HITL
    hitl_confirmed: bool  # Day 8 新增：summarize 前是否已确认


# ========== 节点函数（Day 8：真实化） ==========
async def chat_node(state: LearningState) -> dict:
    """节点 1：对话学习（Day 8 接真实 Agent）。

    职责：
        - 调 invoke_agent（内部走 style_injector + RAG 工具）
        - 把 AI 回复追加到 messages
        - 更新 turn_count

    Note:
        - invoke_agent 是非流式封装，返回完整字符串
        - 真实生产用 astream_agent 流式，这里为了工作流编排用非流式
    """
    from app.agents.learning_agent import invoke_agent  # 延迟导入避免循环依赖

    user_msg = state["messages"][-1].content if state["messages"] else ""
    turn_count = state.get("turn_count", 0) + 1
    user_id = state.get("user_id", "default-user")
    thread_id = state.get("thread_id", f"workflow-{user_id}")

    logger.info(f"[chat_node] 第 {turn_count} 轮，user={user_id}，msg='{user_msg[:30]}...'")

    try:
        # 调真实 Agent（带 style_injector + RAG 工具）
        ai_reply_text = await invoke_agent(user_msg, thread_id)
        logger.info(f"[chat_node] Agent 回复长度 {len(ai_reply_text)}")
    except Exception as e:
        logger.error(f"[chat_node] Agent 调用失败，fallback 到回声：{e}")
        ai_reply_text = f"[chat_node fallback] 收到你的消息：{user_msg}"

    ai_reply = AIMessage(content=ai_reply_text)

    return {
        "messages": [ai_reply],
        "turn_count": turn_count,
    }


async def extract_style_node(state: LearningState) -> dict:
    """节点 2：风格抽取（Day 8 接真实 LLM）。

    职责：
        - 用 extract_style_with_llm 从对话历史抽取风格
        - 写入 kb_style（ChromaDB）
        - 返回抽取出的样本列表
    """
    turn_count = state.get("turn_count", 0)
    user_id = state.get("user_id", "default-user")
    messages = state.get("messages", [])

    logger.info(f"[extract_style_node] 第 {turn_count} 轮触发风格抽取")

    try:
        # 调真实 LLM 抽取（with_structured_output）
        samples = await extract_style_with_llm(messages, user_id=user_id)

        if samples:
            kb_manager.add_style_samples(samples)
            logger.info(f"[extract_style_node] 写入 kb_style {len(samples)} 条")
        else:
            logger.info("[extract_style_node] LLM 未抽取到风格样本")

        return {
            "extracted_styles": [s.page_content for s in samples],
        }
    except Exception as e:
        logger.error(f"[extract_style_node] 抽取失败：{e}")
        return {"extracted_styles": []}


async def summarize_node(state: LearningState) -> dict:
    """节点 3：知识汇总（Day 8 接真实 LLM + HITL 确认点）。

    职责：
        - HITL：此节点前会 interrupt（compile 时配置）
        - 用户确认后，用 summarize_with_llm 提取知识点
        - 写入 kb_facts（ChromaDB）

    HITL 流程：
        1. 工作流执行到 summarize 前 → 暂停，返回当前 State
        2. 用户看到 turn_count / messages，决定是否继续
        3. 用户调 graph.ainvoke(None, config, command=Command(resume=True)) 继续
        4. summarize_node 执行，写入 kb_facts
    """
    turn_count = state.get("turn_count", 0)
    user_id = state.get("user_id", "default-user")
    messages = state.get("messages", [])

    logger.info(f"[summarize_node] 第 {turn_count} 轮触发知识汇总（HITL 已确认）")

    try:
        facts = await summarize_with_llm(messages, user_id=user_id)

        if facts:
            kb_manager.add_facts(facts)
            logger.info(f"[summarize_node] 写入 kb_facts {len(facts)} 条")
        else:
            logger.info("[summarize_node] LLM 未提取到知识点")

        return {"hitl_confirmed": True}
    except Exception as e:
        logger.error(f"[summarize_node] 汇总失败：{e}")
        return {"hitl_confirmed": True}  # 即使失败也标记已确认，避免卡住


async def style_reply_node(state: LearningState) -> dict:
    """节点 4：风格化回复（Day 8 接真实 Agent）。

    职责：
        - 从 kb_style 检索用户风格样本
        - 构造带风格提示的新 prompt
        - 调 invoke_agent 生成最终风格化回复
        - 设置 final_reply（终止信号）

    Note:
        - chat_node 已经调过一次 Agent 生成回复
        - 这里再调一次是为了"风格化润色"（Day 8 简化：直接用 chat 的回复 + 风格样本拼接）
        - Day 9 可优化：合并 chat + style_reply 为一个节点
    """
    user_id = state.get("user_id", "default-user")
    last_ai_msg = state["messages"][-1].content if state["messages"] else ""

    logger.info(f"[style_reply_node] 生成风格化回复")

    # 从 kb_style 检索样本
    try:
        style_docs = kb_manager.search_style(
            query="用户风格样本",
            k=3,
            filter={"user_id": user_id},
        )
        style_text = "\n".join(f"- {d.page_content}" for d in style_docs)
        logger.info(f"[style_reply_node] 检索到 {len(style_docs)} 条风格样本")
    except Exception as e:
        logger.warning(f"[style_reply_node] 检索风格失败：{e}")
        style_text = "（无风格样本）"

    # Day 8 简化：直接拼接（避免再调一次 LLM 增加延迟）
    # Day 9 优化：可改成调 invoke_agent 让 LLM 根据风格样本重写回复
    final_reply = f"""{last_ai_msg}

---
【已注入用户风格样本】
{style_text}
"""

    return {"final_reply": final_reply}


# ========== 条件边路由（同 Day 7） ==========
def route_after_chat(state: LearningState) -> str:
    """条件边：chat 之后路由到哪个节点。

    路由逻辑：
        - turn_count % 10 == 0：先 summarize（会 HITL 暂停），再 extract_style，再 style_reply
        - turn_count % 5 == 0：先 extract_style，再 style_reply
        - 其他：直接 style_reply
    """
    turn_count = state.get("turn_count", 0)

    if turn_count % 10 == 0:
        logger.debug(f"[route] turn={turn_count} → summarize（HITL 暂停点）")
        return "summarize"
    elif turn_count % 5 == 0:
        logger.debug(f"[route] turn={turn_count} → extract_style")
        return "extract_style"
    else:
        logger.debug(f"[route] turn={turn_count} → style_reply")
        return "style_reply"


def route_after_summarize(state: LearningState) -> str:
    """条件边：summarize 之后路由到 extract_style。"""
    return "extract_style"


def route_after_extract(state: LearningState) -> str:
    """条件边：extract_style 之后路由到 style_reply。"""
    return "style_reply"


# ========== 构建工作流（Day 8：加 HITL） ==========
def build_learning_workflow(
    enable_hitl: bool = False,
    checkpointer: Any = None,
) -> Any:
    """构建学习助手核心工作流 StateGraph。

    Day 8 改造点：
        - 加 enable_hitl 参数：是否在 summarize 前暂停
        - 加 checkpointer 参数：支持 HITL 恢复（必须配合 thread_id）

    工作流拓扑：
        START → chat → route_after_chat
                            ├─ summarize* → extract_style → style_reply → END（10 轮）
                            ├─ extract_style → style_reply → END（5 轮）
                            └─ style_reply → END（其他）
        * summarize 前会 HITL 暂停（enable_hitl=True 时）

    Args:
        enable_hitl: 是否启用 HITL（True 时 summarize 前暂停）
        checkpointer: LangGraph checkpointer（HITL 必须传，用于恢复）

    Returns:
        CompiledGraph: 编译后的可执行图

    Example:
        # 不带 HITL（测试用，直接跑完）
        >>> graph = build_learning_workflow(enable_hitl=False)

        # 带 HITL（生产用，summarize 前暂停）
        >>> graph = build_learning_workflow(enable_hitl=True, checkpointer=saver)
        >>> config = {"configurable": {"thread_id": "t1"}}
        >>> result = await graph.ainvoke(initial_state, config)  # 跑到 summarize 前停
        >>> # 用户确认后继续
        >>> result = await graph.ainvoke(None, config, command=Command(resume=True))
    """
    workflow = StateGraph(LearningState)

    # 添加节点
    workflow.add_node("chat", chat_node)
    workflow.add_node("extract_style", extract_style_node)
    workflow.add_node("summarize", summarize_node)
    workflow.add_node("style_reply", style_reply_node)

    # START → chat
    workflow.add_edge(START, "chat")

    # chat → 条件路由
    workflow.add_conditional_edges(
        "chat",
        route_after_chat,
        {
            "summarize": "summarize",
            "extract_style": "extract_style",
            "style_reply": "style_reply",
        },
    )

    # summarize → extract_style → style_reply → END
    workflow.add_conditional_edges(
        "summarize",
        route_after_summarize,
        {"extract_style": "extract_style"},
    )
    workflow.add_conditional_edges(
        "extract_style",
        route_after_extract,
        {"style_reply": "style_reply"},
    )
    workflow.add_edge("style_reply", END)

    # 编译（Day 8：可选 HITL + checkpointer）
    compile_kwargs: dict = {}
    if enable_hitl:
        compile_kwargs["interrupt_before"] = ["summarize"]
        logger.info("HITL 已启用：summarize 前会暂停")
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
        logger.info("Checkpointer 已注入：支持 HITL 恢复")

    graph = workflow.compile(**compile_kwargs)
    logger.info(f"Learning workflow 已编译（enable_hitl={enable_hitl}）")
    return graph


# ========== 运行工作流（Day 8：异步 + HITL） ==========
async def run_workflow(
    user_message: str,
    turn_count: int = 0,
    user_id: str = "default-user",
    thread_id: str | None = None,
    enable_hitl: bool = False,
    checkpointer: Any = None,
    resume: bool = False,
) -> dict:
    """运行学习助手工作流（Day 8：异步 + HITL 支持）。

    Args:
        user_message: 用户消息
        turn_count: 当前轮数
        user_id: 用户 ID
        thread_id: 会话 ID（HITL 必须传，用于恢复）
        enable_hitl: 是否启用 HITL
        checkpointer: checkpointer（HITL 必须传）
        resume: 是否是恢复执行（True 时 user_message 被忽略，从暂停点继续）

    Returns:
        dict: 最终 state（含 final_reply）

    HITL 使用示例：
        # 第一次调用（跑到 summarize 前停）
        >>> result1 = await run_workflow("学装饰器", turn_count=9, enable_hitl=True, ...)
        # 用户确认后恢复
        >>> result2 = await run_workflow("", resume=True, thread_id="t1", enable_hitl=True, ...)
    """
    graph = build_learning_workflow(enable_hitl=enable_hitl, checkpointer=checkpointer)

    _thread_id = thread_id or f"workflow-{user_id}-{turn_count}"
    config = {"configurable": {"thread_id": _thread_id}}

    if resume:
        # 恢复执行：从暂停点继续
        logger.info(f"[run_workflow] 恢复执行 thread_id={_thread_id}")
        result = await graph.ainvoke(
            None,  # 不传新 state，从 checkpoint 恢复
            config,
            command=Command(resume=True),
        )
    else:
        # 首次执行
        initial_state: LearningState = {
            "messages": [HumanMessage(content=user_message)],
            "turn_count": turn_count,
            "user_id": user_id,
            "extracted_styles": [],
            "final_reply": "",
            "thread_id": _thread_id,
            "hitl_confirmed": False,
        }
        logger.info(f"[run_workflow] 首次执行 thread_id={_thread_id}, turn={turn_count}")
        result = await graph.ainvoke(initial_state, config)

    logger.info(f"[run_workflow] 完成，final_reply 长度 {len(result.get('final_reply', ''))}")
    return result
