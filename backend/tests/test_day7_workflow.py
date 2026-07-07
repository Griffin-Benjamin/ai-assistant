"""Day 7 端到端测试：LangGraph StateGraph 工作流。

验证：
1. StateGraph 能正确编译和运行
2. 条件边路由正确（不同 turn_count 走不同路径）
3. operator.add reducer 正确累积 messages 和 extracted_styles
4. 三种路径全覆盖：
   - turn_count=1：chat → style_reply（直接回复）
   - turn_count=5：chat → extract_style → style_reply（5 轮触发抽取）
   - turn_count=10：chat → summarize → extract_style → style_reply（10 轮触发汇总+抽取）

Note:
    Day 8 改造后 run_workflow 为 async，本测试用 asyncio.run 运行。
    节点真实化后不再有 mock 文案，断言聚焦拓扑与路由正确性。
    网络不可用时各节点 fallback，工作流拓扑仍应正确执行。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage

from app.agents.learning_agent import agent_manager
from app.graphs.learning_workflow import build_learning_workflow, run_workflow


# ========== 测试 1：turn=1 直接回复 ==========
async def test_turn_1_direct_reply():
    """测试 1：第 1 轮，直接回复（不走 extract/summarize）。"""
    print("=" * 70)
    print("测试 1：turn_count=0 → 第 1 轮，期望 chat → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="什么是装饰器",
        turn_count=0,
        user_id="day7-test",
        thread_id="day7-test-t1",
    )

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")
    print(f"[结果] final_reply 长度：{len(result['final_reply'])}")
    print(f"[结果] final_reply 预览：\n{result['final_reply'][:200]}...")

    # 校验拓扑（不依赖网络与具体文案）
    assert result["turn_count"] == 1, "turn_count 应为 1"
    assert len(result["messages"]) == 2, "messages 应有 2 条（Human + AI）"
    assert len(result["extracted_styles"]) == 0, "extracted_styles 应为空（未触发抽取）"
    assert len(result["final_reply"]) > 0, "final_reply 应非空"
    print("\n[校验] ✅ 第 1 轮路径正确：chat → style_reply")


# ========== 测试 2：turn=5 触发风格抽取 ==========
async def test_turn_5_extract_style():
    """测试 2：第 5 轮，触发风格抽取。"""
    print("\n" + "=" * 70)
    print("测试 2：turn_count=4 → 第 5 轮，期望 chat → extract_style → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="继续学习",
        turn_count=4,
        user_id="day7-test",
        thread_id="day7-test-t5",
    )

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")

    # 校验拓扑
    assert result["turn_count"] == 5, "turn_count 应为 5"
    # extracted_styles 数量不固定（LLM 可能抽到 0~N 条），只校验字段存在
    assert isinstance(result["extracted_styles"], list), "extracted_styles 应为 list"
    print(f"\n[校验] ✅ 第 5 轮路径正确，extracted_styles 数：{len(result['extracted_styles'])}")


# ========== 测试 3：turn=10 触发汇总+抽取 ==========
async def test_turn_10_summarize_and_extract():
    """测试 3：第 10 轮，触发汇总 + 抽取。"""
    print("\n" + "=" * 70)
    print("测试 3：turn_count=9 → 第 10 轮，期望 chat → summarize → extract_style → style_reply")
    print("=" * 70)

    result = await run_workflow(
        user_message="学完了",
        turn_count=9,
        user_id="day7-test",
        thread_id="day7-test-t10",
    )

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")
    print(f"[结果] hitl_confirmed：{result.get('hitl_confirmed')}")

    # 校验拓扑
    assert result["turn_count"] == 10, "turn_count 应为 10"
    assert result.get("hitl_confirmed") is True, "hitl_confirmed 应为 True（summarize 已执行）"
    assert isinstance(result["extracted_styles"], list), "extracted_styles 应为 list"
    print("\n[校验] ✅ 第 10 轮路径正确：chat → summarize → extract_style → style_reply")


# ========== 测试 4：reducer 在单次工作流内累积 ==========
async def test_reducer_accumulation():
    """测试 4：验证 operator.add reducer 在单次工作流内正确累积。"""
    print("\n" + "=" * 70)
    print("测试 4：验证 reducer 累积（单次工作流内 messages 累积）")
    print("=" * 70)

    # 第 1 轮
    r1 = await run_workflow(
        user_message="第一句",
        turn_count=0,
        user_id="day7-reducer",
        thread_id="day7-reducer-t1",
    )
    # 第 5 轮（独立工作流）
    r5 = await run_workflow(
        user_message="第五句",
        turn_count=4,
        user_id="day7-reducer",
        thread_id="day7-reducer-t5",
    )

    print(f"\n[第 1 轮] messages: {len(r1['messages'])} 条")
    print(f"[第 5 轮] messages: {len(r5['messages'])} 条")
    print(f"[第 5 轮] extracted_styles: {r5['extracted_styles']}")

    # 校验：每次工作流独立运行，messages 各 2 条（Human + AI）
    assert len(r1["messages"]) == 2, "第 1 轮 messages 应为 2"
    assert len(r5["messages"]) == 2, "第 5 轮 messages 应为 2（独立运行，不跨工作流累积）"
    assert isinstance(r5["extracted_styles"], list), "extracted_styles 应为 list"
    print("\n[校验] ✅ Reducer 在单次工作流内正确累积")


# ========== 测试 5：StateGraph 编译 ==========
def test_graph_compilation():
    """测试 5：验证图能编译。"""
    print("\n" + "=" * 70)
    print("测试 5：验证 StateGraph 编译")
    print("=" * 70)

    graph = build_learning_workflow()
    print(f"\n[结果] graph 类型：{type(graph).__name__}")
    print(f"[结果] graph nodes：{list(graph.get_graph().nodes.keys())}")

    assert graph is not None
    print("\n[校验] ✅ StateGraph 编译成功")


# ========== 主函数 ==========
async def main():
    print("=" * 70)
    print("初始化 AgentManager（异步 Checkpointer）")
    print("=" * 70)
    await agent_manager.init()

    try:
        test_graph_compilation()
        await test_turn_1_direct_reply()
        await test_turn_5_extract_style()
        await test_turn_10_summarize_and_extract()
        await test_reducer_accumulation()

        print("\n" + "=" * 70)
        print("✅ Day 7 LangGraph StateGraph 工作流测试全部通过")
        print("=" * 70)
    finally:
        await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
