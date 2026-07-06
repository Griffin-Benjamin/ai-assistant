"""Day 6 简化版 RAG 评估脚本（参考 RAGAS 6 指标）。

RAGAS 完整版需要 OpenAI API 评估 LLM（cost 高），这里用规则评估演示思路：
- Context Precision（上下文精确度）：检索结果中相关条目的比例
- Context Recall（上下文召回率）：期望关键词被检索到的比例
- Faithfulness（忠实度）：回答中关键词是否来自检索内容（不编造）
- Response Relevancy（回答相关性）：回答是否覆盖期望答案要点

完整 RAGAS 6 指标对照：
| 指标 | 完整 RAGAS（LLM 评估） | 本脚本（规则评估） |
|------|----------------------|-----------------|
| Context Precision  | LLM 判断每条 context 是否相关 | 关键词命中比例 |
| Context Recall     | LLM 判断期望答案是否被 context 覆盖 | 期望关键词被检索比例 |
| Faithfulness       | LLM 判断回答是否基于 context | 回答关键词在 context 中的比例 |
| Response Relevancy | LLM 判断回答是否切题 | 期望要点在回答中的比例 |
| Noise Sensitivity  | LLM 判断噪声影响 | （本脚本不评估） |
| Answer Correctness | LLM 对比回答和标准答案 | （本脚本不评估） |

为什么用规则评估而不是 LLM 评估：
1. 不消耗 LLM API 配额（RAGAS 完整评估 10 个 query 约花 $0.5-1）
2. 评估速度快（规则评估 < 1s，LLM 评估 10+ 分钟）
3. 开发期足够（生产可换 RAGAS 完整版）
4. 缺点：规则评估不如 LLM 评估准确（无法判断语义相似度，只能匹配关键词）

测试数据：
    准备 3 个测试 query + 期望关键词，跑评估，输出 4 个指标分数。
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.learning_agent import agent_manager, astream_agent
from app.services.document_loader import ingest_markdown_to_facts
from app.services.kb_manager import kb_manager
from app.tools.rag_tools import search_knowledge_base


# ========== 测试数据集（query + 期望关键词） ==========
TEST_CASES = [
    {
        "query": "Python 装饰器是什么",
        "expected_keywords": ["装饰器", "高阶函数", "wrapper", "func"],
        "expected_in_context": ["装饰器", "高阶函数"],  # 期望检索结果包含
        "expected_in_answer": ["装饰器", "高阶函数"],   # 期望回答包含
    },
    {
        "query": "装饰器怎么用",
        "expected_keywords": ["@", "wrapper", "log_call"],
        "expected_in_context": ["@", "wrapper"],
        "expected_in_answer": ["@", "wrapper"],
    },
    {
        "query": "装饰器易错点",
        "expected_keywords": ["wrapper", "返回", "参数", "*args"],
        "expected_in_context": ["wrapper", "*args"],
        "expected_in_answer": ["wrapper"],
    },
]

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
3. 多个装饰器从下往上应用
"""


def clear_kb_facts():
    """清空 kb_facts。"""
    facts = kb_manager.facts
    try:
        old_data = facts._collection.get()
        old_ids = old_data["ids"]
        if old_ids:
            facts.delete(old_ids)
    except Exception:
        pass


def write_temp_note() -> Path:
    """写临时笔记。"""
    tmp_dir = Path(tempfile.gettempdir()) / "ai-assistant-eval"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    note_path = tmp_dir / "python-decorator.md"
    note_path.write_text(NOTE_CONTENT, encoding="utf-8")
    return note_path


# ========== 评估指标实现 ==========
def evaluate_context_precision(retrieved_docs: list, expected_keywords: list[str]) -> float:
    """Context Precision：检索结果中包含期望关键词的比例。

    计算：检索到的 docs 中，包含期望关键词的 doc 数 / 总检索 doc 数
    取值：[0, 1]，越高越好（1.0 = 每条检索结果都相关）
    """
    if not retrieved_docs:
        return 0.0
    relevant_count = 0
    for doc in retrieved_docs:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        if any(kw in content for kw in expected_keywords):
            relevant_count += 1
    return relevant_count / len(retrieved_docs)


def evaluate_context_recall(retrieved_docs: list, expected_keywords: list[str]) -> float:
    """Context Recall：期望关键词被检索结果覆盖的比例。

    计算：被检索到的期望关键词数 / 总期望关键词数
    取值：[0, 1]，越高越好（1.0 = 所有期望关键词都被检索到）
    """
    if not expected_keywords:
        return 1.0
    all_content = " ".join(
        doc.page_content if hasattr(doc, "page_content") else str(doc)
        for doc in retrieved_docs
    )
    hit = sum(1 for kw in expected_keywords if kw in all_content)
    return hit / len(expected_keywords)


def evaluate_faithfulness(answer: str, retrieved_docs: list) -> float:
    """Faithfulness：回答中的关键词是否来自检索内容（不编造）。

    计算：回答中的关键词（来自期望集合）在检索内容中的比例
    取值：[0, 1]，越高越好（1.0 = 回答完全基于检索内容）
    """
    if not retrieved_docs or not answer:
        return 0.0
    all_content = " ".join(
        doc.page_content if hasattr(doc, "page_content") else str(doc)
        for doc in retrieved_docs
    )
    # 取回答中实际出现的关键词，看其中多少在 context 中
    answer_keywords = [kw for kw in ["装饰器", "高阶函数", "wrapper", "func", "@", "*args"] if kw in answer]
    if not answer_keywords:
        return 1.0  # 没有关键词无法评估，给满分
    in_context = sum(1 for kw in answer_keywords if kw in all_content)
    return in_context / len(answer_keywords)


def evaluate_response_relevancy(answer: str, expected_in_answer: list[str]) -> float:
    """Response Relevancy：回答是否覆盖期望要点。

    计算：回答中包含的期望要点数 / 总期望要点数
    取值：[0, 1]，越高越好（1.0 = 回答覆盖所有期望要点）
    """
    if not expected_in_answer:
        return 1.0
    hit = sum(1 for kw in expected_in_answer if kw in answer)
    return hit / len(expected_in_answer)


async def evaluate_single(test_case: dict, thread_id: str) -> dict:
    """评估单个测试用例。"""
    query = test_case["query"]

    # 1. 调 RAG 工具检索
    retrieved_docs = kb_manager.search_facts(
        query=query, k=3, filter={"user_id": "default-user"}
    )

    # 2. 调 Agent 生成回答
    chunks = []
    async for token in astream_agent(query, thread_id):
        chunks.append(token)
    answer = "".join(chunks)

    # 3. 计算 4 个指标
    context_precision = evaluate_context_precision(
        retrieved_docs, test_case["expected_in_context"]
    )
    context_recall = evaluate_context_recall(
        retrieved_docs, test_case["expected_in_context"]
    )
    faithfulness = evaluate_faithfulness(answer, retrieved_docs)
    response_relevancy = evaluate_response_relevancy(
        answer, test_case["expected_in_answer"]
    )

    return {
        "query": query,
        "retrieved_count": len(retrieved_docs),
        "answer_len": len(answer),
        "context_precision": context_precision,
        "context_recall": context_recall,
        "faithfulness": faithfulness,
        "response_relevancy": response_relevancy,
        "answer_preview": answer[:120] + "..." if len(answer) > 120 else answer,
    }


async def main():
    print("=" * 70)
    print("Day 6 RAG 评估脚本（简化版 RAGAS）")
    print("=" * 70)

    # 1. 初始化
    print("\n[步骤 1] 初始化 AgentManager")
    await agent_manager.init()

    # 2. 准备数据
    print("\n[步骤 2] 清空 kb_facts + 入库笔记")
    clear_kb_facts()
    note_path = write_temp_note()
    ingest_result = ingest_markdown_to_facts(
        file_path=note_path,
        user_id="default-user",
        subject="Python",
        tags=["decorator"],
    )
    print(f"  入库 {ingest_result['chunks']} 个 chunk")

    # 3. 跑评估
    print("\n[步骤 3] 跑评估（3 个测试用例）")
    results = []
    for i, tc in enumerate(TEST_CASES):
        print(f"\n--- 测试用例 {i+1}/{len(TEST_CASES)} ---")
        print(f"  query: {tc['query']}")
        thread_id = f"day6-eval-{i}"
        result = await evaluate_single(tc, thread_id)
        results.append(result)
        print(f"  retrieved: {result['retrieved_count']} 条")
        print(f"  answer_len: {result['answer_len']} 字")
        print(f"  Context Precision:  {result['context_precision']:.2f}")
        print(f"  Context Recall:     {result['context_recall']:.2f}")
        print(f"  Faithfulness:       {result['faithfulness']:.2f}")
        print(f"  Response Relevancy: {result['response_relevancy']:.2f}")

    # 4. 汇总
    print("\n" + "=" * 70)
    print("汇总评估结果")
    print("=" * 70)
    avg_cp = sum(r["context_precision"] for r in results) / len(results)
    avg_cr = sum(r["context_recall"] for r in results) / len(results)
    avg_f = sum(r["faithfulness"] for r in results) / len(results)
    avg_rr = sum(r["response_relevancy"] for r in results) / len(results)

    print(f"\n{'指标':<25} {'平均分':<10} {'说明'}")
    print(f"{'-'*60}")
    print(f"{'Context Precision':<25} {avg_cp:<10.2f} 检索结果中相关条目比例")
    print(f"{'Context Recall':<25} {avg_cr:<10.2f} 期望关键词被检索比例")
    print(f"{'Faithfulness':<25} {avg_f:<10.2f} 回答关键词来自context比例")
    print(f"{'Response Relevancy':<25} {avg_rr:<10.2f} 回答覆盖期望要点比例")
    print(f"{'-'*60}")
    overall = (avg_cp + avg_cr + avg_f + avg_rr) / 4
    print(f"{'综合分':<25} {overall:<10.2f}")

    print("\n评估解读：")
    print("  - 0.9+：优秀，RAG 系统工作良好")
    print("  - 0.7-0.9：良好，部分指标可优化（如换 embedding 或调切分）")
    print("  - < 0.7：需优化，检查切分策略/embedding 模型/检索 k 值")
    print("\n注意：本脚本是规则评估，生产环境建议用 RAGAS 完整版（LLM 评估）")

    await agent_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
