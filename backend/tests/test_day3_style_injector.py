"""Day 3 端到端测试（Day 4：异步改造版）。

验证 style_injector middleware 是否真的把样本拼到 system_prompt。
Day 4 改造点：同步 → 异步（asyncio.run + await astream_agent）

测试策略：
  1. 先不注入样本，发一个问题，观察日志"无风格样本"
  2. 调 seed_mock_style() 注入 3 条样本
  3. 再发同一个问题（新 thread_id），观察日志"风格注入成功"
  4. 看回答内容是否体现注入的风格（用类比、用"你"、出题）
  5. 测试会话管理：history 查询 + delete 清空
"""
import asyncio
import sys
from pathlib import Path

# 确保能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.learning_agent import (
    _STORE,
    agent_manager,
    astream_agent,
    clear_chat_session,
    get_chat_history,
    seed_mock_style,
)

QUESTION = "用一句话解释什么是 API"
TEST_THREAD_1 = "day4-test-no-style"
TEST_THREAD_2 = "day4-test-with-style"
TEST_THREAD_3 = "day4-test-history"


async def ask(thread_id: str) -> str:
    """发一个问题，把回答拼成完整字符串打印。"""
    print(f"\n>>> 提问 [thread_id={thread_id}]：{QUESTION}")
    chunks = []
    async for token in astream_agent(QUESTION, thread_id):
        chunks.append(token)
    answer = "".join(chunks)
    print(f"<<< 回答（{len(answer)} 字）：\n{answer}")
    return answer


async def main():
    # Day 4：必须先 await agent_manager.init() 初始化异步 Checkpointer
    print("=" * 70)
    print("初始化 AgentManager（异步 Checkpointer）")
    print("=" * 70)
    await agent_manager.init()

    # 清空 store 保证测试干净
    try:
        _STORE.delete(("style", "default-user"))
    except Exception:
        pass

    print("\n" + "=" * 70)
    print("阶段 1：未注入风格样本")
    print("=" * 70)
    await ask(TEST_THREAD_1)

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
    await ask(TEST_THREAD_2)

    print("\n" + "=" * 70)
    print("阶段 3：会话管理 - 查询历史")
    print("=" * 70)
    # 再发一题到 thread_2，累积多轮历史
    print(f"\n>>> 追问 [thread_id={TEST_THREAD_2}]：再补充一句")
    async for token in astream_agent("再补充一句", TEST_THREAD_2):
        pass  # 只为累积历史，不打印

    history = await get_chat_history(TEST_THREAD_2)
    print(f"\n[校验] {TEST_THREAD_2} 历史消息数：{len(history)}")
    for i, msg in enumerate(history):
        print(f"  [{i}] role={msg['role']}, type={msg['type']}, "
              f"content={msg['content'][:60]!r}...")

    print("\n" + "=" * 70)
    print("阶段 4：会话管理 - 清空会话")
    print("=" * 70)
    success = await clear_chat_session(TEST_THREAD_2)
    print(f"[校验] 清空 {TEST_THREAD_2}：{success}")

    # 验证清空后历史为空
    history_after = await get_chat_history(TEST_THREAD_2)
    print(f"[校验] 清空后历史消息数：{len(history_after)}")

    print("\n" + "=" * 70)
    print("测试完成。判断标准：")
    print("  - 日志应出现 '风格注入成功：拼入 3 条样本'")
    print("  - 第二次回答应多用类比、用'你'而非'您'、可能带自检题")
    print("  - history 应返回 4 条消息（2 轮对话）")
    print("  - clear 后 history 应为 0 条")
    print("=" * 70)

    # 关闭连接
    await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
