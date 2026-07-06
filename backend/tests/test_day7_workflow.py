"""Day 7 端到端测试：LangGraph StateGraph 工作流。

验证：
1. StateGraph 能正确编译和运行
2. 条件边路由正确（不同 turn_count 走不同路径）
3. operator.add reducer 正确累积 messages 和 extracted_styles
4. 三种路径全覆盖：
   - turn_count=1：chat → style_reply（直接回复）
   - turn_count=5：chat → extract_style → style_reply（5 轮触发抽取）
   - turn_count=10：chat → summarize → extract_style → style_reply（10 轮触发汇总+抽取）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage

from app.graphs.learning_workflow import build_learning_workflow, run_workflow


def test_turn_1_direct_reply():
    """测试 1：第 1 轮，直接回复（不走 extract/summarize）。"""
    print("=" * 70)
    print("测试 1：turn_count=0 → 第 1 轮，期望 chat → style_reply")
    print("=" * 70)

    result = run_workflow("什么是装饰器", turn_count=0, user_id="day7-test")

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")
    print(f"[结果] final_reply 长度：{len(result['final_reply'])}")
    print(f"[结果] final_reply 预览：\n{result['final_reply'][:200]}...")

    # 校验
    assert result["turn_count"] == 1, "turn_count 应为 1"
    assert len(result["messages"]) == 2, "messages 应有 2 条（Human + AI）"
    assert len(result["extracted_styles"]) == 0, "extracted_styles 应为空（未触发抽取）"
    assert "回声" in result["final_reply"], "final_reply 应含 chat_node 的回声"
    print("\n[校验] ✅ 第 1 轮路径正确：chat → style_reply")


def test_turn_5_extract_style():
    """测试 2：第 5 轮，触发风格抽取。"""
    print("\n" + "=" * 70)
    print("测试 2：turn_count=4 → 第 5 轮，期望 chat → extract_style → style_reply")
    print("=" * 70)

    result = run_workflow("继续学习", turn_count=4, user_id="day7-test")

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")

    # 校验
    assert result["turn_count"] == 5, "turn_count 应为 5"
    assert len(result["extracted_styles"]) == 1, "extracted_styles 应有 1 条（触发了抽取）"
    assert "第 5 轮抽取" in result["extracted_styles"][0], "应含第 5 轮标记"
    print("\n[校验] ✅ 第 5 轮路径正确：chat → extract_style → style_reply")


def test_turn_10_summarize_and_extract():
    """测试 3：第 10 轮，触发汇总 + 抽取。"""
    print("\n" + "=" * 70)
    print("测试 3：turn_count=9 → 第 10 轮，期望 chat → summarize → extract_style → style_reply")
    print("=" * 70)

    result = run_workflow("学完了", turn_count=9, user_id="day7-test")

    print(f"\n[结果] messages 数：{len(result['messages'])}")
    print(f"[结果] turn_count：{result['turn_count']}")
    print(f"[结果] extracted_styles：{result['extracted_styles']}")

    # 校验
    assert result["turn_count"] == 10, "turn_count 应为 10"
    assert len(result["extracted_styles"]) == 1, "extracted_styles 应有 1 条"
    assert "第 10 轮抽取" in result["extracted_styles"][0], "应含第 10 轮标记"
    print("\n[校验] ✅ 第 10 轮路径正确：chat → summarize → extract_style → style_reply")


def test_reducer_accumulation():
    """测试 4：验证 operator.add reducer 正确累积。"""
    print("\n" + "=" * 70)
    print("测试 4：验证 reducer 累积（多轮后 messages 累积）")
    print("=" * 70)

    # 第 1 轮
    r1 = run_workflow("第一句", turn_count=0, user_id="day7-reducer")
    # 第 5 轮
    r5 = run_workflow("第五句", turn_count=4, user_id="day7-reducer")

    print(f"\n[第 1 轮] messages: {len(r1['messages'])} 条")
    print(f"[第 5 轮] messages: {len(r5['messages'])} 条")
    print(f"[第 5 轮] extracted_styles: {r5['extracted_styles']}")

    # 校验：每次工作流独立运行，messages 各 2 条（Human + AI）
    # extracted_styles 在第 5 轮触发，累积 1 条
    assert len(r1["messages"]) == 2
    assert len(r5["messages"]) == 2  # 独立运行，不跨工作流累积
    assert len(r5["extracted_styles"]) == 1
    print("\n[校验] ✅ Reducer 在单次工作流内正确累积")


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


if __name__ == "__main__":
    test_graph_compilation()
    test_turn_1_direct_reply()
    test_turn_5_extract_style()
    test_turn_10_summarize_and_extract()
    test_reducer_accumulation()

    print("\n" + "=" * 70)
    print("✅ Day 7 LangGraph StateGraph 工作流测试全部通过")
    print("=" * 70)
