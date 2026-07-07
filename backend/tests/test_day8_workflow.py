"""Day 8 端到端测试：核心链路 5 步跑通 + HITL。

验证：
1. 不带 HITL：turn=1 → chat → style_reply（真实 Agent 回复，网络不可用时 fallback）
2. 不带 HITL：turn=5 → chat → extract_style → style_reply（LLM 抽取，网络不可用时 fallback）
3. 不带 HITL：turn=10 → chat → summarize → extract_style → style_reply（LLM 汇总）
4. 带 HITL：turn=10 → chat → 暂停在 summarize 前 → resume → 继续

Note:
    - 测试需要真实 LLM API Key（DeepSeek）
    - 网络不可用时各节点会 fallback，工作流拓扑仍应正确执行
    - HITL 测试用 MemorySaver（内存 checkpointer），验证暂停/恢复机制
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agents.learning_agent import agent_manager
from app.graphs.learning_workflow import build_learning_workflow, run_workflow


# ========== 测试 1：turn=1 直接回复 ==========
async def test_turn_1_direct_reply():
    """turn=1 → chat → style_reply。"""
    print("=" * 70)
    print("测试 1：turn_count=0 → 第 1 轮，期望 chat → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="用一句话解释什么是 API",
        turn_count=0,
        user_id="day8-test",
        thread_id="day8-test-t1",
    )

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")
    print(f"[结果] final_reply 预览：\n{result['final_reply'][:300]}...")

    # 校验拓扑（不依赖网络）
    assert result["turn_count"] == 1, "turn_count 应为 1"
    assert len(result["messages"]) == 2, "messages 应有 2 条"
    assert len(result["extracted_styles"]) == 0, "extracted_styles 应为空"
    assert len(result["final_reply"]) > 0, "final_reply 应非空"
    print("\n[校验] ✅ 第 1 轮路径正确：chat → style_reply")


# ========== 测试 2：turn=5 触发风格抽取 ==========
async def test_turn_5_extract_style():
    """turn=5 → chat → extract_style → style_reply。"""
    print("\n" + "=" * 70)
    print("测试 2：turn=4 → 第 5 轮，期望 chat → extract_style → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="再给我讲讲装饰器的用法",
        turn_count=4,
        user_id="day8-test",
        thread_id="day8-test-t5",
    )

    print(f"\n[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")

    # 校验拓扑
    assert result["turn_count"] == 5, "turn_count 应为 5"
    print(f"\n[校验] ✅ 第 5 轮路径正确，extracted_styles 数：{len(result['extracted_styles'])}")


# ========== 测试 3：turn=10 触发汇总+抽取 ==========
async def test_turn_10_summarize():
    """turn=10 → chat → summarize → extract_style → style_reply。"""
    print("\n" + "=" * 70)
    print("测试 3：turn=9 → 第 10 轮，期望 chat → summarize → extract_style → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="总结一下今天学的",
        turn_count=9,
        user_id="day8-test",
        thread_id="day8-test-t10",
    )

    print(f"\n[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")
    print(f"[结果] hitl_confirmed：{result.get('hitl_confirmed')}")

    # 校验拓扑
    assert result["turn_count"] == 10, "turn_count 应为 10"
    assert result.get("hitl_confirmed") is True, "hitl_confirmed 应为 True（summarize 已执行）"
    print(f"\n[校验] ✅ 第 10 轮路径正确，summarize 已执行")


# ========== 测试 4：HITL 暂停 + 恢复 ==========
async def test_hitl_pause_and_resume():
    """turn=10 + HITL → chat → 暂停在 summarize 前 → resume → 继续。"""
    print("\n" + "=" * 70)
    print("测试 4：HITL 暂停 + 恢复")
    print("=" * 70)

    checkpointer = MemorySaver()
    thread_id = "day8-test-hitl"

    # 阶段 1：首次执行，应跑到 summarize 前暂停
    print("\n--- 阶段 1：首次执行（应暂停在 summarize 前）---")
    graph = build_learning_workflow(enable_hitl=True, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [HumanMessage(content="学完了，总结一下")],
        "turn_count": 9,
        "user_id": "day8-test",
        "extracted_styles": [],
        "final_reply": "",
        "thread_id": thread_id,
        "hitl_confirmed": False,
    }

    result1 = await graph.ainvoke(initial_state, config)

    print(f"[阶段 1 结果] turn_count：{result1.get('turn_count')}")
    print(f"[阶段 1 结果] messages 数：{len(result1.get('messages', []))}")
    print(f"[阶段 1 结果] final_reply：'{result1.get('final_reply', '')[:50]}'")

    # 校验：应暂停在 summarize 前
    # 暂停时 final_reply 应为空（还没走到 style_reply）
    assert result1.get("turn_count") == 10, "turn_count 应已更新到 10"
    assert result1.get("final_reply", "") == "", "HITL 暂停时 final_reply 应为空"
    print("[校验] ✅ 工作流正确暂停在 summarize 前")

    # 阶段 2：恢复执行
    print("\n--- 阶段 2：恢复执行（从 summarize 继续）---")
    result2 = await graph.ainvoke(None, config, command=Command(resume=True))

    print(f"[阶段 2 结果] turn_count：{result2.get('turn_count')}")
    print(f"[阶段 2 结果] extracted_styles：{result2.get('extracted_styles')}")
    print(f"[阶段 2 结果] hitl_confirmed：{result2.get('hitl_confirmed')}")
    print(f"[阶段 2 结果] final_reply 长度：{len(result2.get('final_reply', ''))}")

    # 校验：应跑完
    assert result2.get("hitl_confirmed") is True, "hitl_confirmed 应为 True"
    assert len(result2.get("final_reply", "")) > 0, "恢复后 final_reply 应非空"
    print("[校验] ✅ HITL 恢复后工作流正确跑完")


# ========== 主函数 ==========
async def main():
    print("=" * 70)
    print("初始化 AgentManager（异步 Checkpointer）")
    print("=" * 70)
    await agent_manager.init()

    try:
        await test_turn_1_direct_reply()
        await test_turn_5_extract_style()
        await test_turn_10_summarize()
        await test_hitl_pause_and_resume()

        print("\n" + "=" * 70)
        print("✅ Day 8 核心链路 5 步跑通 + HITL 测试全部通过")
        print("=" * 70)
    finally:
        await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
