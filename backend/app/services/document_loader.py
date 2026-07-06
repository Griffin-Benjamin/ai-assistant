"""文档加载与切分服务（Day 6：知识库入库）。

提供：
- ``load_markdown``：加载 Markdown 文件为 Document
- ``load_pdf``：加载 PDF 文件为 Document（PyPDFLoader）
- ``split_documents``：递归字符切分
- ``ingest_markdown_to_facts``：端到端：加载 md → 切分 → 入库 kb_facts

RAG 链路五步对应：
    加载（TextLoader/PyPDFLoader）→ 切分（RecursiveCharacterTextSplitter）
    → 入库（kb_manager.add_facts，自动 Embedding + 存 ChromaDB）
    → 检索（@tool search_knowledge_base，Day 6 实现）
    → 注入 prompt（Agent 自动处理 ToolMessage）

切分策略：
    - chunk_size=500 字符（中文知识点通常 200-800 字）
    - chunk_overlap=50 字符（避免切到关键句中间）
    - separators=["\n\n", "\n", "。", "！", "？", "，", " ", ""]（按中文标点优先切分）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from loguru import logger

from app.services.kb_manager import kb_manager


# ========== 切分器（中文友好） ==========
def _make_splitter(chunk_size: int = 500, chunk_overlap: int = 50) -> RecursiveCharacterTextSplitter:
    """创建递归字符切分器（中文友好）。

    Args:
        chunk_size: 每个切片最大字符数
        chunk_overlap: 切片间重叠字符数（避免切到关键句中间）

    Returns:
        RecursiveCharacterTextSplitter

    Note:
        separators 按优先级：先按段落（\\n\\n）切，太大再按行（\\n）切，
        再按句号切，最后按空格切。这样能尽量保持语义完整。
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        keep_separator=True,
    )


# ========== 加载器 ==========
def load_markdown(file_path: str | Path) -> list[Document]:
    """加载 Markdown 文件为 Document 列表。

    Args:
        file_path: md 文件路径

    Returns:
        list[Document]: 每个文档对应文件全部内容（page_content 是文本，
                       metadata 含 source/title）

    Note:
        简化版：不解析 md 结构（标题/代码块/列表），整文件作为一个 Document。
        Day 8 可升级：用 markdown 库解析出标题层级，每个章节单独一个 Document。
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    if path.suffix.lower() not in (".md", ".markdown"):
        logger.warning(f"文件不是 markdown：{path}")

    text = path.read_text(encoding="utf-8")
    title = path.stem  # 文件名（不含扩展名）作为标题
    doc = Document(
        page_content=text,
        metadata={
            "source": str(path),
            "title": title,
            "file_type": "markdown",
        },
    )
    logger.info(f"加载 markdown：{path.name} → {len(text)} 字符")
    return [doc]


def load_pdf(file_path: str | Path) -> list[Document]:
    """加载 PDF 文件为 Document 列表。

    Args:
        file_path: pdf 文件路径

    Returns:
        list[Document]: PyPDFLoader 每页一个 Document

    Note:
        需要 pypdf 依赖（已在 pyproject.toml 中）
    """
    from langchain_community.document_loaders import PyPDFLoader  # 延迟 import 避免无 pdf 时报错

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    loader = PyPDFLoader(str(path))
    docs = loader.load()
    logger.info(f"加载 PDF：{path.name} → {len(docs)} 页")
    return docs


# ========== 切分 ==========
def split_documents(
    documents: list[Document],
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[Document]:
    """递归字符切分文档列表。

    Args:
        documents: 原始文档列表
        chunk_size: 每个切片最大字符数
        chunk_overlap: 切片间重叠字符数

    Returns:
        list[Document]: 切分后的文档列表（保留原 metadata，新增 chunk_index）

    Note:
        - 切分后会保留原 metadata（source/title 等）
        - 切分后每个 chunk 的 page_content 是切片文本
        - 切片大小是字符数（不是 token 数），中文 1 字符 ≈ 1-2 token
    """
    splitter = _make_splitter(chunk_size, chunk_overlap)
    chunks = splitter.split_documents(documents)

    # 给每个 chunk 加序号（方便追溯）
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i
        chunk.metadata["total_chunks"] = len(chunks)

    logger.info(f"切分文档：{len(documents)} 个原文档 → {len(chunks)} 个 chunk"
                f"（chunk_size={chunk_size}, overlap={chunk_overlap}）")
    return chunks


# ========== 端到端入库 ==========
def ingest_markdown_to_facts(
    file_path: str | Path,
    user_id: str = "default-user",
    subject: str | None = None,
    tags: list[str] | None = None,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> dict[str, Any]:
    """端到端：加载 md → 切分 → 入库 kb_facts。

    Args:
        file_path: md 文件路径
        user_id: 用户 ID（用于 metadata 过滤）
        subject: 学科分类（如 "Python"），None 则用文件名
        tags: 标签列表
        chunk_size: 切片大小
        chunk_overlap: 切片重叠

    Returns:
        dict: 入库结果统计 {
            "file": 文件名,
            "total_chars": 原文字符数,
            "chunks": 切片数,
            "ids": ChromaDB 文档 ID 列表,
        }

    Example:
        >>> result = ingest_markdown_to_facts("notes/python-decorator.md", subject="Python")
        >>> print(f"入库 {result['chunks']} 个 chunk")
    """
    path = Path(file_path)
    logger.info(f"开始入库 markdown：{path.name}")

    # 1. 加载
    docs = load_markdown(path)
    total_chars = sum(len(d.page_content) for d in docs)

    # 2. 增强 metadata
    _subject = subject or path.stem
    _tags_str = ",".join(tags) if tags else ""
    for doc in docs:
        doc.metadata.update({
            "user_id": user_id,
            "subject": _subject,
            "tags": _tags_str,
            "source": "md_import",
        })

    # 3. 切分
    chunks = split_documents(docs, chunk_size, chunk_overlap)

    # 4. 入库
    ids = kb_manager.add_facts(chunks)

    logger.info(f"入库完成：{path.name} → {len(chunks)} chunks, {len(ids)} IDs")
    return {
        "file": path.name,
        "total_chars": total_chars,
        "chunks": len(chunks),
        "ids": ids,
    }
