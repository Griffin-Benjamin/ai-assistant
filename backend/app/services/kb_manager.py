"""三库分离架构管理器（Day 5：RAG 知识库构建）。

提供：
- ``KBManager``：管理三个 Chroma collection（kb_facts / kb_style / kb_thinking）
- ``ChromaDefaultEmbeddings``：chromadb 默认 embedding 适配 langchain 接口
- 三库 CRUD：add / search / delete

三库分离架构（核心设计）：
    kb_facts    —— 客观知识点库（错题、笔记内容）    → Day 6 RAG 检索
    kb_style    —— 用户语言风格样本库（短语、句式）  → Day 8 风格化回复
    kb_thinking —— 用户推理路径样本库（拆解角度）    → Day 8 风格化回复

为什么三库分离（不混在一起）：
    1. 检索语义不同：facts 检索"知识内容"，style 检索"说话方式"，thinking 检索"思考路径"
    2. 注入时机不同：facts 在 RAG 工具调用时注入，style/thinking 在 system_prompt 注入
    3. 数据量控制：style/thinking 样本需要精简（设上限），facts 可大量累积
    4. 置信度衰减：style/thinking 有置信度衰减机制，facts 按时间/掌握度管理

Embedding 选型：
    用 chromadb 自带的 DefaultEmbeddingFunction（all-MiniLM-L6-v2 onnx 版）：
    - 384 维向量，体积小速度快
    - 首次自动下载 ~80MB onnx 模型到 ~/.cache/chroma/
    - 离线可用，无需 API key，无需 GPU
    - 适合开发期；生产可换 bge-m3 / text-embedding-3-large

持久化：
    三个 collection 共用 ./data/chroma/ 目录，但 collection_name 不同
    Chroma 自动管理底层 SQLite + 向量索引文件
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from chromadb.utils import embedding_functions
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from loguru import logger


# ========== Embedding 适配器 ==========
class ChromaDefaultEmbeddings(Embeddings):
    """把 chromadb 默认 embedding function 适配成 langchain Embeddings 接口。

    chromadb 自带 all-MiniLM-L6-v2 onnx 模型（384 维），首次使用自动下载到
    ~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/，之后离线可用。

    适配原因：
        langchain_chroma.Chroma 的 embedding_function 参数要求 langchain 的
        Embeddings 类型（有 embed_documents / embed_query 方法），而 chromadb
        原生的 DefaultEmbeddingFunction 不满足这个接口，需要包一层。
    """

    def __init__(self) -> None:
        self._ef = embedding_functions.DefaultEmbeddingFunction()
        logger.info("ChromaDefaultEmbeddings 已初始化（all-MiniLM-L6-v2 onnx, 384 维）")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量向量化文档。"""
        return self._ef(texts)

    def embed_query(self, text: str) -> list[float]:
        """向量化单条查询。"""
        return self._ef([text])[0]


# ========== 三库分离管理器 ==========
class KBManager:
    """三库分离架构管理器：管理 kb_facts / kb_style / kb_thinking 三个 Chroma collection。

    生命周期：
        - 开发期：模块级单例 kb_manager，import 时初始化
        - 生产：可按用户隔离（每个 user_id 一套 collection 或 metadata 过滤）

    Note:
        - 三个 collection 共用同一持久化目录 ./data/chroma/
        - 共用同一 embedding 模型（384 维 all-MiniLM-L6-v2）
        - 每个 collection 独立 CRUD，互不干扰
    """

    # collection 名称常量（对应三库分离架构）
    COLLECTION_FACTS = "kb_facts"
    COLLECTION_STYLE = "kb_style"
    COLLECTION_THINKING = "kb_thinking"

    def __init__(self, persist_dir: str = "./data/chroma") -> None:
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._embeddings = ChromaDefaultEmbeddings()

        # 初始化三个 collection（懒加载，首次访问时创建）
        self._facts: Chroma | None = None
        self._style: Chroma | None = None
        self._thinking: Chroma | None = None

        logger.info(f"KBManager 已初始化：persist_dir={self._persist_dir.absolute()}")

    @property
    def facts(self) -> Chroma:
        """kb_facts collection：客观知识点库（错题、笔记内容）。"""
        if self._facts is None:
            self._facts = self._create_collection(self.COLLECTION_FACTS)
        return self._facts

    @property
    def style(self) -> Chroma:
        """kb_style collection：用户语言风格样本库（短语、句式）。"""
        if self._style is None:
            self._style = self._create_collection(self.COLLECTION_STYLE)
        return self._style

    @property
    def thinking(self) -> Chroma:
        """kb_thinking collection：用户推理路径样本库（拆解角度、关联习惯）。"""
        if self._thinking is None:
            self._thinking = self._create_collection(self.COLLECTION_THINKING)
        return self._thinking

    def _create_collection(self, name: str) -> Chroma:
        """创建或加载一个 Chroma collection。

        Args:
            name: collection 名称

        Returns:
            Chroma: LangChain 封装的 Chroma 向量库实例

        Note:
            - 同名 collection 再次创建会加载已有数据（持久化）
            - collection_name 是底层 chromadb 的命名空间隔离
        """
        return Chroma(
            collection_name=name,
            embedding_function=self._embeddings,
            persist_directory=str(self._persist_dir),
        )

    # ========== kb_facts：客观知识点 ==========
    def add_facts(self, documents: list[Document]) -> list[str]:
        """添加客观知识点到 kb_facts。

        Args:
            documents: 文档列表，metadata 建议含 user_id/subject/tags/source

        Returns:
            list[str]: 添加的文档 ID 列表
        """
        ids = self.facts.add_documents(documents)
        logger.info(f"kb_facts 添加 {len(ids)} 条知识点")
        return ids

    def search_facts(self, query: str, k: int = 3,
                     filter: dict | None = None) -> list[Document]:
        """从 kb_facts 检索相关知识点。

        Args:
            query: 查询文本
            k: 返回 top-k
            filter: metadata 过滤（如 {"user_id": "default-user"}）

        Returns:
            list[Document]: 相关知识点文档列表
        """
        results = self.facts.similarity_search(query=query, k=k, filter=filter)
        logger.debug(f"kb_facts 检索 '{query[:30]}...' → {len(results)} 条")
        return results

    # ========== kb_style：用户语言风格 ==========
    def add_style_samples(self, documents: list[Document]) -> list[str]:
        """添加风格样本到 kb_style。

        Args:
            documents: 文档列表，metadata 建议含 user_id/confidence

        Returns:
            list[str]: 添加的文档 ID 列表
        """
        ids = self.style.add_documents(documents)
        logger.info(f"kb_style 添加 {len(ids)} 条风格样本")
        return ids

    def search_style(self, query: str, k: int = 3,
                     filter: dict | None = None) -> list[Document]:
        """从 kb_style 检索相关风格样本。

        Args:
            query: 查询文本
            k: 返回 top-k
            filter: metadata 过滤

        Returns:
            list[Document]: 相关风格样本文档列表
        """
        results = self.style.similarity_search(query=query, k=k, filter=filter)
        logger.debug(f"kb_style 检索 '{query[:30]}...' → {len(results)} 条")
        return results

    # ========== kb_thinking：用户推理路径 ==========
    def add_thinking_samples(self, documents: list[Document]) -> list[str]:
        """添加推理路径样本到 kb_thinking。

        Args:
            documents: 文档列表，metadata 建议含 user_id/confidence

        Returns:
            list[str]: 添加的文档 ID 列表
        """
        ids = self.thinking.add_documents(documents)
        logger.info(f"kb_thinking 添加 {len(ids)} 条推理样本")
        return ids

    def search_thinking(self, query: str, k: int = 3,
                        filter: dict | None = None) -> list[Document]:
        """从 kb_thinking 检索相关推理样本。

        Args:
            query: 查询文本
            k: 返回 top-k
            filter: metadata 过滤

        Returns:
            list[Document]: 相关推理样本文档列表
        """
        results = self.thinking.similarity_search(query=query, k=k, filter=filter)
        logger.debug(f"kb_thinking 检索 '{query[:30]}...' → {len(results)} 条")
        return results

    # ========== 通用工具 ==========
    def delete_from_collection(self, collection_name: str, ids: list[str]) -> None:
        """从指定 collection 删除文档。

        Args:
            collection_name: COLLECTION_FACTS / COLLECTION_STYLE / COLLECTION_THINKING
            ids: 要删除的文档 ID 列表
        """
        collection_map = {
            self.COLLECTION_FACTS: self.facts,
            self.COLLECTION_STYLE: self.style,
            self.COLLECTION_THINKING: self.thinking,
        }
        if collection_name not in collection_map:
            raise ValueError(f"未知 collection: {collection_name}")
        collection_map[collection_name].delete(ids)
        logger.info(f"{collection_name} 删除 {len(ids)} 条文档")

    def get_collection_stats(self) -> dict[str, int]:
        """获取三个 collection 的文档数量统计。

        Returns:
            dict: {collection_name: count}
        """
        stats = {}
        for name, collection in [
            (self.COLLECTION_FACTS, self.facts),
            (self.COLLECTION_STYLE, self.style),
            (self.COLLECTION_THINKING, self.thinking),
        ]:
            # Chroma 的底层 collection 对象有 count() 方法
            try:
                count = collection._collection.count()
            except Exception:
                count = -1
            stats[name] = count
        return stats


# ========== 全局单例 ==========
kb_manager = KBManager()
logger.info("kb_manager 全局单例已创建")
