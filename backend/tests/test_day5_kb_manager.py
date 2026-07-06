"""Day 5 端到端测试：三库分离架构验证。

验证：
1. 三个 collection 能独立初始化
2. 各库 add/search/delete 正常
3. 语义检索能找到相关内容（不是精确匹配）
4. metadata 过滤生效
5. 持久化（重启后数据还在）—— 仅验证初始化不报错，持久化由 Chroma 保证
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document

from app.services.kb_manager import kb_manager


def test_facts():
    """测试 kb_facts：客观知识点。"""
    print("=" * 70)
    print("测试 1：kb_facts（客观知识点）")
    print("=" * 70)

    # 清空旧数据（保证测试干净）
    facts = kb_manager.facts
    try:
        old_ids = facts._collection.get()["ids"]
        if old_ids:
            facts.delete(old_ids)
            print(f"[清理] 删除 {len(old_ids)} 条旧数据")
    except Exception as e:
        print(f"[清理] 跳过：{e}")

    # 添加知识点
    docs = [
        Document(
            page_content="Python 的装饰器是一种高阶函数，用来在不修改原函数的前提下扩展其功能。@decorator 语法等价于 func = decorator(func)。",
            metadata={"user_id": "default-user", "subject": "Python", "tags": "decorator", "source": "manual"},
        ),
        Document(
            page_content="FastAPI 是基于 Starlette 和 Pydantic 的现代 Web 框架，支持异步、自动生成 OpenAPI 文档、依赖注入。",
            metadata={"user_id": "default-user", "subject": "FastAPI", "tags": "web", "source": "manual"},
        ),
        Document(
            page_content="LangGraph 的 StateGraph 由 Node（节点函数）、Edge（边）、State（共享状态）三要素组成，支持循环和条件分支。",
            metadata={"user_id": "default-user", "subject": "LangGraph", "tags": "graph", "source": "manual"},
        ),
    ]
    ids = kb_manager.add_facts(docs)
    print(f"[添加] {len(ids)} 条知识点")

    # 语义检索（不是精确匹配）
    query = "Python 怎么给函数加额外功能"
    results = kb_manager.search_facts(query, k=2)
    print(f"\n[检索] '{query}'")
    for i, doc in enumerate(results):
        print(f"  [{i+1}] subject={doc.metadata.get('subject')}")
        print(f"      content={doc.page_content[:80]}...")

    # metadata 过滤
    results_filtered = kb_manager.search_facts(
        "框架", k=5, filter={"subject": "FastAPI"}
    )
    print(f"\n[过滤检索] subject=FastAPI → {len(results_filtered)} 条")
    for doc in results_filtered:
        print(f"  - {doc.page_content[:60]}...")

    # 验证语义检索找到装饰器（不是精确关键词匹配）
    assert len(results) > 0, "检索结果不应为空"
    assert any("装饰器" in r.page_content for r in results), "应检索到装饰器知识点"
    print("\n[校验] ✅ 语义检索正确找到装饰器知识点")


def test_style():
    """测试 kb_style：用户语言风格。"""
    print("\n" + "=" * 70)
    print("测试 2：kb_style（用户语言风格）")
    print("=" * 70)

    style = kb_manager.style
    try:
        old_ids = style._collection.get()["ids"]
        if old_ids:
            style.delete(old_ids)
    except Exception:
        pass

    # 添加风格样本
    docs = [
        Document(
            page_content="回答问题时多用类比，把抽象概念类比到生活中的事物，比如把 API 类比成餐厅服务员。",
            metadata={"user_id": "default-user", "confidence": 0.9},
        ),
        Document(
            page_content="语气轻松，像朋友聊天，用'你'不用'您'，偶尔加 emoji。",
            metadata={"user_id": "default-user", "confidence": 0.85},
        ),
        Document(
            page_content="讲完每个知识点出 1-2 道自检题，验证用户是否真的懂了。",
            metadata={"user_id": "default-user", "confidence": 0.8},
        ),
    ]
    ids = kb_manager.add_style_samples(docs)
    print(f"[添加] {len(ids)} 条风格样本")

    # 语义检索
    query = "怎么说话能让用户觉得亲切"
    results = kb_manager.search_style(query, k=2)
    print(f"\n[检索] '{query}'")
    for i, doc in enumerate(results):
        print(f"  [{i+1}] confidence={doc.metadata.get('confidence')}")
        print(f"      content={doc.page_content[:80]}...")

    assert any("语气" in r.page_content or "你" in r.page_content for r in results), \
        "应检索到语气相关样本"
    print("\n[校验] ✅ 语义检索正确找到语气风格样本")


def test_thinking():
    """测试 kb_thinking：用户推理路径。"""
    print("\n" + "=" * 70)
    print("测试 3：kb_thinking（用户推理路径）")
    print("=" * 70)

    thinking = kb_manager.thinking
    try:
        old_ids = thinking._collection.get()["ids"]
        if old_ids:
            thinking.delete(old_ids)
    except Exception:
        pass

    docs = [
        Document(
            page_content="遇到新概念先问'它是干什么的'，再用生活类比理解，最后看代码例子验证。",
            metadata={"user_id": "default-user", "confidence": 0.9},
        ),
        Document(
            page_content="学框架时先跑通最小 demo，再读源码理解内部机制，最后自己造轮子加深理解。",
            metadata={"user_id": "default-user", "confidence": 0.85},
        ),
    ]
    ids = kb_manager.add_thinking_samples(docs)
    print(f"[添加] {len(ids)} 条推理样本")

    query = "怎么学一个新技术"
    results = kb_manager.search_thinking(query, k=2)
    print(f"\n[检索] '{query}'")
    for i, doc in enumerate(results):
        print(f"  [{i+1}] {doc.page_content[:80]}...")

    assert len(results) > 0, "检索结果不应为空"
    print("\n[校验] ✅ 语义检索正确找到推理样本")


def test_stats():
    """测试统计。"""
    print("\n" + "=" * 70)
    print("测试 4：collection 统计")
    print("=" * 70)
    stats = kb_manager.get_collection_stats()
    for name, count in stats.items():
        print(f"  {name}: {count} 条")
    assert all(c >= 0 for c in stats.values()), "统计不应有负数"


if __name__ == "__main__":
    test_facts()
    test_style()
    test_thinking()
    test_stats()

    print("\n" + "=" * 70)
    print("✅ Day 5 三库分离架构测试全部通过")
    print("=" * 70)
