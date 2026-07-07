# AI 学习助手

> 基于 LangChain + LangGraph 的个性化学习助手，核心差异化能力是**用户风格克隆**。
>
> 9 天从零系统掌握 LangChain/LangGraph 并独立开发智能体应用的实战项目。

## 核心能力

1. **用户自选模型 + 自定义学习规则** — 支持 DeepSeek / OpenAI / Claude 等 OpenAI 兼容协议模型
2. **三库分离架构** — `kb_facts`（客观知识点）/ `kb_style`（语言风格样本）/ `kb_thinking`（推理路径样本）
3. **用户风格克隆** — 抽取用户语言风格 + 推理路径，回复时模拟用户习惯（核心差异化卖点）
4. **自动汇总入库** — 定时从对话中抽取错题/笔记/心得到知识库，每次汇总时更新
5. **LangGraph 工作流编排** — StateGraph 编排对话/抽取/汇总/回复 5 步链路 + HITL 人工确认

## 技术栈

| 层 | 技术 |
|----|------|
| LLM 编排 | LangChain 0.3 + LangGraph 0.2 |
| Web 框架 | FastAPI + sse-starlette（SSE 流式） |
| 短期记忆 | AsyncSqliteSaver（aiosqlite） |
| 长期记忆 | ChromaDB（向量库，all-MiniLM-L6-v2 onnx 384 维） |
| 业务数据 | SQLite + SQLAlchemy 2.0 |
| 包管理 | uv |
| 日志 | loguru |
| 配置 | pydantic-settings + .env |

## 项目结构

```
ai-assistant/
├── backend/                       # 后端（FastAPI + LangChain + LangGraph）
│   ├── app/
│   │   ├── agents/                # Agent 层
│   │   │   └── learning_agent.py  # 学习助手 Agent（style_injector + RAG + AsyncCheckpointer）
│   │   ├── api/v1/                # API 接口层
│   │   │   ├── chat.py            # SSE 流式对话 + 会话管理
│   │   │   ├── personas.py        # 人格管理
│   │   │   ├── projects.py        # 项目管理
│   │   │   ├── tasks.py           # 任务管理
│   │   │   └── knowledge_tree.py  # 知识树
│   │   ├── graphs/                # LangGraph 工作流
│   │   │   └── learning_workflow.py  # 核心 5 步链路 StateGraph + HITL
│   │   ├── services/              # 业务服务层
│   │   │   ├── kb_manager.py      # 三库分离管理器（ChromaDB）
│   │   │   ├── llm_extractors.py  # LLM 结构化抽取（with_structured_output）
│   │   │   ├── document_loader.py # 文档加载 + 切分
│   │   │   └── ...
│   │   ├── tools/                 # Agent 工具
│   │   │   └── rag_tools.py       # @tool search_knowledge_base（Agentic RAG）
│   │   ├── models/                # 数据模型
│   │   └── main.py                # FastAPI 入口（lifespan 管理 AgentManager）
│   ├── tests/                     # 端到端测试（Day 3-8 各一份）
│   ├── .env.example               # 环境变量模板
│   └── pyproject.toml             # 依赖（uv 管理）
├── docs/
│   ├── architecture.md            # 架构文档
│   └── learning-notes/            # 9 天学习笔记
└── web/                           # 前端原型（HTML/CSS/JS）
```

## 快速开始

### 1. 环境准备

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（包管理工具）

### 2. 安装依赖

```bash
cd ai-assistant/backend
uv sync
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key（必填）
# LLM_API_KEY=sk-xxx
```

### 4. 启动后端

```bash
uv run uvicorn app.main:app --reload --port 8001
```

启动后访问：
- 健康检查：http://localhost:8001/health
- Swagger 文档：http://localhost:8001/docs

### 5. 运行测试

```bash
# Day 5：三库分离架构测试
uv run python tests/test_day5_kb_manager.py

# Day 6：Agentic RAG 测试
uv run python tests/test_day6_rag_agent.py

# Day 7：StateGraph 工作流测试（不需要 LLM）
uv run python tests/test_day7_workflow.py

# Day 8：核心链路 5 步 + HITL 测试（需要 LLM，网络不可用时走 fallback）
uv run python tests/test_day8_workflow.py
```

## 核心架构

### 三库分离（核心设计）

| 库 | 用途 | 注入时机 | 数据量控制 |
|----|------|---------|----------|
| `kb_facts` | 客观知识点（错题/笔记/心得） | RAG 工具调用时检索 | 大量累积 |
| `kb_style` | 用户语言风格样本 | `style_injector` middleware 注入 system_prompt | 设上限 + 置信度衰减 |
| `kb_thinking` | 用户推理路径样本 | Day 9+ 注入 system_prompt | 设上限 |

**为什么三库分离**：
1. 检索语义不同：facts 检索"知识内容"，style 检索"说话方式"，thinking 检索"思考路径"
2. 注入时机不同：facts 在 RAG 工具调用时注入，style/thinking 在 system_prompt 注入
3. 数据量控制：style/thinking 需要精简（设上限），facts 可大量累积

### LangGraph 核心工作流

```
START → chat → route_after_chat
                    ├─ summarize* → extract_style → style_reply → END（10 轮）
                    ├─ extract_style → style_reply → END（5 轮）
                    └─ style_reply → END（其他）
* summarize 前会 HITL 暂停（enable_hitl=True 时）
```

**5 步链路**：
1. **chat** — 对话学习（调真实 Agent，带 style_injector + RAG 工具）
2. **extract_style** — 风格抽取（LLM `with_structured_output`，每 5 轮触发）
3. **summarize** — 知识汇总（LLM `with_structured_output`，每 10 轮触发，HITL 确认）
4. **update_kb** — 三库更新（在 extract/summarize 节点内完成写入）
5. **style_reply** — 风格化回复（检索 kb_style + 生成最终回复）

### 数据流

```
用户消息 → Agent.astream（stream_mode="messages"）
  → style_injector middleware 拦截模型调用
    → kb_manager.search_style 语义检索风格样本
    → 拼到 system_prompt 末尾
  → LLM 决定是否调 search_knowledge_base 工具
    → 调工具：从 kb_facts 检索 → ToolMessage 返回
    → 不调：直接用内置知识回答
  → AsyncCheckpointer 自动读写历史（thread_id 隔离）
  → SSE yield 给前端
```

## 9 天学习路线

| Day | 主题 | 产出 |
|-----|------|------|
| 1 | LangChain 核心组件 | 笔记 + DeepTutor 代码地图 |
| 2 | Agent 入门实战 | 最小可用 Agent + SSE 接口 |
| 3 | Runtime + Middleware | style_injector 风格注入中间件 |
| 4 | 异步 Checkpointer + 多 Agent | AsyncSqliteSaver + 会话管理接口 |
| 5 | RAG 知识库构建 | 三库分离架构（KBManager + ChromaDB） |
| 6 | RAG Agent + 评估 | Agentic RAG（@tool）+ RAGAS 评估 |
| 7 | LangGraph Workflow | StateGraph 4 节点 + 3 条件边 |
| 8 | 核心链路 5 步 + HITL | 真实化 + interrupt_before + Command resume |
| 9 | 整合 + GitHub + 面试 | README + 面试 Q&A + 推送 |

## 关键技术点

- **wrap_model_call middleware**：拦截模型调用，动态修改 system_prompt（风格注入）
- **AsyncSqliteSaver + aiosqlite**：异步 Checkpointer，不阻塞事件循环
- **with_structured_output**：Pydantic schema → tool → LLM 强制 JSON 输出
- **interrupt_before + Command(resume=True)**：LangGraph HITL 暂停/恢复
- **operator.add reducer**：累积型 State 字段（messages、extracted_styles）
- **延迟导入**：避免 `learning_workflow ↔ learning_agent` 循环依赖

## 面试 Q&A 速览

- **Agent 是什么**：LLM + 工具调用 + 记忆的循环，自主决策何时调工具、何时回答
- **三库分离为什么**：检索语义/注入时机/数据量控制都不同，混在一起会互相污染
- **风格克隆怎么实现**：style_injector middleware 从 kb_style 检索样本 → 拼到 system_prompt
- **HITL 怎么做**：compile(interrupt_before=["summarize"]) + Command(resume=True)
- **with_structured_output 原理**：Pydantic → JSON Schema → tool → LLM 调 tool 输出 JSON

详细 Q&A 见 `docs/learning-notes/` 各 Day 笔记的「面试问题」章节。

## 风险提示

- **网络代理**：LLM 调用需要稳定的网络，代理端口拒绝时会走 fallback（质量降低）
- **SQLite 并发**：单进程内并发 OK，多 worker 部署需换 Postgres
- **模型能力差异**：用户选 DeepSeek 和选 GPT-4o，工具调用能力差很多，需「模型能力矩阵」标识
- **风格克隆伦理**：克隆的是"学习风格"而非"人格"，文档里必须写清楚边界

## License

MIT
