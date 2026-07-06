"""Day 6 端到端测试：Agentic RAG（RAG 工具 + Agent）。

验证：
1. markdown 笔记能正确入库到 kb_facts（加载 + 切分 + 入库）
2. Agent 能自主决定是否调 search_knowledge_base 工具
3. 检索到笔记内容后，回答能引用笔记原文
4. 没有笔记时，Agent 用内置知识直接回答

测试策略：
  阶段 1：清空 kb_facts + 入库 1 个 markdown 笔记
  阶段 2：问"我笔记里怎么写的装饰器" → 期望调工具 + 引用笔记
  阶段 3：问"什么是 Python" → 期望不调工具，直接回答（通用知识）
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.learning_agent import agent_manager, astream_agent
from app.services.document_loader import ingest_markdown_to_facts
from app.services.kb_manager import kb_manager

# 测试用的 markdown 笔记内容
NOTE_CONTENT = """# Python 装饰器学习笔记

## 核心概念

装饰器（decorator）是一种高阶函数，用来在不修改原函数的前提下扩展其功能。
@decorator 语法等价于 `func = decorator(func)`。

## 实际例子

```python
def log_call(func):
    def wrapper(*args, **kwargs):
        print(f"调用 {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

@log_call
def say_hello():
    print("hello")
```

## 易错点

1. 装饰器要返回 wrapper 函数本身，不是调用它
2. wrapper 要用 *args, **kwargs 接收任意参数
3. 多个装饰器从下往上应用（@log_call @timer 等价于 log_call(timer(func))）
"""

QUESTION_NOTE = "我笔记里怎么写的装饰器？"
QUESTION_GENERAL = "Python 的列表和元组有什么区别？"
TEST_THREAD_NOTE = "day6-test-with-rag"
TEST_THREAD_GENERAL = "day6-test-no-rag"


def clear_kb_facts():
    """清空 kb_facts 保证测试干净。"""
    facts = kb_manager.facts
    try:
        old_data = facts._collection.get()
        old_ids = old_data["ids"]
        if old_ids:
            facts.delete(old_ids)
            print(f"[清理] 删除 kb_facts 中 {len(old_ids)} 条旧数据")
        else:
            print("[清理] kb_facts 已空")
    except Exception as e:
        print(f"[清理] 跳过：{e}")


def write_temp_note() -> Path:
    """写一个临时 markdown 笔记文件。"""
    tmp_dir = Path(tempfile.gettempdir()) / "ai-assistant-test"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    note_path = tmp_dir / "python-decorator.md"
    note_path.write_text(NOTE_CONTENT, encoding="utf-8")
    print(f"[准备] 写入临时笔记：{note_path}")
    return note_path


async def ask(thread_id: str, question: str) -> str:
    """发一个问题，把回答拼成完整字符串打印。"""
    print(f"\n>>> 提问 [thread_id={thread_id}]：{question}")
    chunks = []
    async for token in astream_agent(question, thread_id):
        chunks.append(token)
    answer = "".join(chunks)
    print(f"<<< 回答（{len(answer)} 字）：\n{answer}")
    return answer


async def main():
    print("=" * 70)
    print("Day 6 端到端测试：Agentic RAG")
    print("=" * 70)

    # 1. 初始化 AgentManager
    print("\n[步骤 1] 初始化 AgentManager")
    await agent_manager.init()

    # 2. 清空 kb_facts + 准备笔记
    print("\n[步骤 2] 清空 kb_facts + 写入临时笔记")
    clear_kb_facts()
    note_path = write_temp_note()

    # 3. 入库 markdown 笔记
    print("\n[步骤 3] 入库 markdown 笔记到 kb_facts")
    result = ingest_markdown_to_facts(
        file_path=note_path,
        user_id="default-user",
        subject="Python",
        tags=["decorator", "function"],
    )
    print(f"[校验] 入库结果：{result}")

    # 验证 kb_facts 能查到
    items = kb_manager.search_facts(
        query="装饰器",
        k=5,
        filter={"user_id": "default-user"},
    )
    print(f"[校验] kb_manager.search_facts 查到 {len(items)} 条")
    for i, doc in enumerate(items[:2]):
        print(f"  [{i+1}] subject={doc.metadata.get('subject')}, "
              f"chunk_index={doc.metadata.get('chunk_index')}")
        print(f"      {doc.page_content[:80]}...")

    # 4. 阶段 1：问笔记内容（应调工具）
    print("\n" + "=" * 70)
    print("阶段 1：问笔记内容（期望：调 search_knowledge_base 工具）")
    print("=" * 70)
    answer1 = await ask(TEST_THREAD_NOTE, QUESTION_NOTE)

    # 5. 阶段 2：问通用知识（不应调工具）
    print("\n" + "=" * 70)
    print("阶段 2：问通用知识（期望：不调工具，直接回答）")
    print("=" * 70)
    answer2 = await ask(TEST_THREAD_GENERAL, QUESTION_GENERAL)

    # 6. 判断标准
    print("\n" + "=" * 70)
    print("判断标准：")
    print("  - 阶段 1 日志应出现 '[RAG 工具] 检索 kb_facts：query=...'")
    print("  - 阶段 1 回答应引用笔记内容（如'高阶函数'、'wrapper'等关键词）")
    print("  - 阶段 2 日志不应出现 '[RAG 工具]'")
    print("  - 阶段 2 回答是通用 Python 知识（列表可变/元组不可变）")
    print("=" * 70)

    await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
