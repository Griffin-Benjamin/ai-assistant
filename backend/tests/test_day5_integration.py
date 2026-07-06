"""Day 5 集成测试：style_injector + ChromaDB 端到端验证。

验证 Day 5 改造（风格样本从 InMemoryStore 切到 ChromaDB）后整体流程正常。

测试策略：
  1. 清空 kb_style collection（保证测试干净）
  2. 不注入样本，发一个问题 → 日志应显示"无风格样本"
  3. 调 seed_mock_style() 注入 3 条样本到 ChromaDB
  4. 验证 kb_manager.search_style 能查到样本
  5. 再发同一个问题（新 thread_id）→ 日志应显示"风格注入成功：拼入 3 条样本"
  6. 看回答内容是否体现注入的风格（用类比、用"你"、出题）

Note: 需要配置 LLM_API_KEY，会真实调用 DeepSeek API。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.learning_agent import (
    agent_manager,
    astream_agent,
    seed_mock_style,
)
from app.services.kb_manager import kb_manager

QUESTION = "用一句话解释什么是 API"
TEST_THREAD_1 = "day5-test-no-style"
TEST_THREAD_2 = "day5-test-with-style"


def clear_kb_style():
    """清空 kb_style collection 保证测试干净。"""
    style = kb_manager.style
    try:
        old_data = style._collection.get()
        old_ids = old_data["ids"]
        if old_ids:
            style.delete(old_ids)
            print(f"[清理] 删除 kb_style 中 {len(old_ids)} 条旧数据")
        else:
            print("[清理] kb_style 已空")
    except Exception as e:
        print(f"[清理] 跳过：{e}")


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
    print("=" * 70)
    print("Day 5 集成测试：style_injector + ChromaDB")
    print("=" * 70)

    # 1. 初始化 AgentManager（异步 Checkpointer）
    print("\n[步骤 1] 初始化 AgentManager")
    await agent_manager.init()

    # 2. 清空 kb_style
    print("\n[步骤 2] 清空 kb_style collection")
    clear_kb_style()

    # 3. 阶段 1：无样本
    print("\n" + "=" * 70)
    print("阶段 1：未注入风格样本（应原样放行）")
    print("=" * 70)
    await ask(TEST_THREAD_1)

    # 4. 注入样本到 ChromaDB
    print("\n" + "=" * 70)
    print("阶段 2：注入 mock 风格样本到 ChromaDB")
    print("=" * 70)
    ids = seed_mock_style("default-user")
    print(f"[校验] seed_mock_style 返回 {len(ids)} 条 ID")

    # 验证 kb_manager 能查到
    items = kb_manager.search_style(
        query="风格样本",
        k=10,
        filter={"user_id": "default-user"},
    )
    print(f"[校验] kb_manager.search_style 查到 {len(items)} 条")
    for i, doc in enumerate(items):
        print(f"  [{i+1}] {doc.page_content[:60]}...")

    # 5. 阶段 3：有样本，新 thread_id
    print("\n" + "=" * 70)
    print("阶段 3：有样本（应风格注入成功）")
    print("=" * 70)
    await ask(TEST_THREAD_2)

    print("\n" + "=" * 70)
    print("判断标准：")
    print("  - 阶段 1 日志：'无风格样本，原样放行'")
    print("  - 阶段 3 日志：'风格注入成功：拼入 3 条样本（来自 kb_style ChromaDB）'")
    print("  - 阶段 3 回答：多用类比、用'你'而非'您'、可能带自检题")
    print("=" * 70)

    await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
