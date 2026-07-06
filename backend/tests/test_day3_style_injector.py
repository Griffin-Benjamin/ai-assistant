"""Day 3 端到端测试：验证 style_injector middleware 是否真的把样本拼到 system_prompt。

测试策略：
  1. 先不注入样本，发一个问题，观察日志"无风格样本"
  2. 调 seed_mock_style() 注入 3 条样本
  3. 再发同一个问题（新 thread_id），观察日志"风格注入成功"
  4. 看回答内容是否体现注入的风格（用类比、用"你"、出题）
"""
import sys
from pathlib import Path

# 确保能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.learning_agent import (
    _STORE,
    build_agent,
    seed_mock_style,
)
from langchain_core.messages import HumanMessage

# 清空 store 保证测试干净
try:
    _STORE.delete(("style", "default-user"))
except Exception:
    pass

agent = build_agent()

QUESTION = "用一句话解释什么是 API"
TEST_THREAD_1 = "day3-test-no-style"
TEST_THREAD_2 = "day3-test-with-style"


def ask(thread_id: str):
    """发一个问题，把回答拼成完整字符串打印。"""
    print(f"\n>>> 提问 [thread_id={thread_id}]：{QUESTION}")
    chunks = []
    config = {"configurable": {"thread_id": thread_id}}
    for chunk, _meta in agent.stream(
        {"messages": [HumanMessage(content=QUESTION)]},
        config,
        stream_mode="messages",
    ):
        if hasattr(chunk, "content") and chunk.content:
            chunks.append(chunk.content)
    answer = "".join(chunks)
    print(f"<<< 回答（{len(answer)} 字）：\n{answer}")
    return answer


print("=" * 70)
print("阶段 1：未注入风格样本")
print("=" * 70)
ask(TEST_THREAD_1)

print("\n" + "=" * 70)
print("阶段 2：注入 mock 风格样本后")
print("=" * 70)
seed_mock_style("default-user")

# 验证 store 里确实有数据
items = _STORE.search(("style", "default-user"), query="风格", limit=10)
print(f"\n[校验] Store 中样本数：{len(items)}")
for it in items:
    print(f"  - key={it.key}, value={it.value}")

print()
ask(TEST_THREAD_2)

print("\n" + "=" * 70)
print("测试完成。判断标准：")
print("  - 日志应出现 '风格注入成功：拼入 3 条样本'")
print("  - 第二次回答应多用类比、用'你'而非'您'、可能带自检题")
print("=" * 70)
