# Code Agent

基于 LangGraph 状态机的多语言程序开发智能体，支持项目分析、代码开发、代码审查、网页读取和普通对话。当前架构组合了 Router、Plan、ReAct、Verify、Review 与 Skill 插件体系。

## 特性

- **组合式 Agent 架构**：任务分类路由 + 执行计划 + ReAct 工具调用 + 验证 + 代码审查。
- **Plan 开发流程**：开发任务会先生成结构化执行计划，再按计划逐步实现。
- **Tool Calling ReAct**：通过 `LLM → tool_calls → ToolMessage → LLM` 循环调用真实工具。
- **多模型适配**：支持 DeepSeek / GLM 等 OpenAI 兼容 API，API Key 从环境变量读取。
- **结构化输出**：基于 Pydantic 定义分类、探索、设计、计划、审查等输出 schema。
- **核心工具集**：项目扫描、文件读写、精确编辑、代码搜索、语义搜索、Python/Java 执行、Git 操作、代码审查等。
- **Skill 插件体系**：通过 `skills/` 目录扩展能力，内置 `web_reader` 网页读取 skill。
- **安全拦截层**：Hook 系统拦截危险代码执行、危险文件写入等操作。
- **一致性校验**：防止模型编造工具执行结果，要求网页读取、代码执行等场景调用真实工具。
- **持久化中间件**：向量检索基于 Chroma 向量库、会话记忆基于 LangGraph SqliteSaver，索引与对话历史均落盘，进程重启不丢失。

## 项目结构

```text
code_agent/
├── dev_agent.py              # 主入口，交互式 REPL
├── eval_harness.py           # 自动化评估框架
├── core/                     # 核心基础设施
│   ├── config.py             # 模型、超时、安全规则和 skill 配置
│   ├── state.py              # AgentState + Pydantic 结构化输出模型
│   ├── hooks.py              # Hook 安全拦截器
│   └── llm.py                # LLM 封装与结构化输出
├── agent/                    # Agent 编排逻辑
│   ├── graph.py              # LangGraph 状态图
│   ├── agents.py             # explorer / architect / reviewer 提示词
│   ├── lang_skills.py        # Python / SQL / Java 语言技能提示
│   └── skill_loader.py       # Skill 自动发现与加载
├── tools/                    # 工具实现与 LangChain 适配
│   ├── file_ops.py           # scan_project / read_file / write_file / edit_file
│   ├── search.py             # search_code / semantic_search
│   ├── execution.py          # execute_python / execute_java
│   ├── analysis.py           # analyze_python / analyze_java / analyze_sql / code_review
│   ├── git_ops.py            # git_status / git_diff / git_commit / git_checkout
│   ├── langchain_adapter.py  # LangChain @tool 适配层
│   └── semantic_search.py    # 语义代码搜索（Chroma 向量库 + 嵌入）
├── skills/                   # 外部 Skill 插件
│   └── web_reader/           # 网页读取工具 read_webpage
└── web/                      # Web 界面
    ├── server.py             # FastAPI 后端（SSE 流式）
    ├── index.html            # 单页前端
    └── app.js                # 前端逻辑
```

## 状态图流程

```text
用户输入
  ↓
classify_task
  ↓
按 task_type 路由
  ├─ analyze  → explore_project → generate_report → END
  ├─ develop  → explore_project → design_solutions → plan_execution → implement_code → verify_result → review_code → END
  ├─ review   → review_code → END
  └─ chat     → chat_respond → END
```

开发任务的核心链路：

```text
Router 分类
  → Explore 探索项目
  → Architect 设计方案
  → Plan 生成执行计划
  → ReAct 调用工具实现
  → Verify 验证结果
  → Review 代码审查
```

验证失败且重试次数小于 3 时，会回到 `design_solutions` 重新设计并再次进入计划/实现流程。

## 核心工具

| 分类 | 工具 | 说明 |
|------|------|------|
| 文件操作 | `scan_project` | 扫描项目目录结构，识别语言和框架 |
| 文件操作 | `read_file` | 读取文件内容 |
| 文件操作 | `write_file` | 写入或创建文件 |
| 文件操作 | `edit_file` | 精确编辑已有文件，支持文本替换、行范围替换、函数替换 |
| 代码搜索 | `search_code` | 正则搜索代码 |
| 代码搜索 | `semantic_search` | 基于自然语言的语义代码搜索 |
| 代码执行 | `execute_python` | 沙箱执行 Python 代码 |
| 代码执行 | `execute_java` | 编译运行 Java 代码 |
| 项目分析 | `analyze_python` | 分析 Python 项目 |
| 项目分析 | `analyze_java` | 分析 Java 项目 |
| 项目分析 | `analyze_sql` | 分析 SQL 脚本 |
| 代码审查 | `code_review` | 从简洁性、正确性、规范性审查代码 |
| Git | `git_status` | 查看 Git 状态 |
| Git | `git_diff` | 查看 Git 差异 |
| Git | `git_commit` | 提交变更 |
| Git | `git_checkout` | 切换分支、创建分支或恢复文件 |
| 网页读取 | `read_webpage` | 读取网页正文并提取内容 |

## 安装

```bash
pip install langchain-core langchain-openai langgraph requests pydantic
# 持久化中间件：Chroma 向量库 + LangGraph SQLite 检查点
pip install chromadb langgraph-checkpoint-sqlite
# 可选：本地嵌入兜底（未配置在线 Embedding API 时使用）
pip install sentence-transformers
```

## 配置

API Key 不应写入代码，使用环境变量配置：

```bash
export DEEPSEEK_API_KEY="your-deepseek-api-key"
export GLM_API_KEY="your-zhipu-api-key"
# 嵌入 API（RAG 向量化，默认走 OpenAI 兼容 /embeddings 端点）
export EMBEDDING_BASE_URL="https://open.bigmodel.cn/api/paas/v4"
export EMBEDDING_API_KEY="your-embedding-api-key"
export EMBEDDING_MODEL="embedding-3"
```

在 `core/config.py` 中通过 `ACTIVE_MODEL` 切换模型：

```python
ACTIVE_MODEL = "deepseek"  # 或 "glm"
```

## 持久化与中间件

所有持久化产物默认落在项目根目录的 `.cache/`（可用环境变量 `CODE_AGENT_PERSIST_ROOT` 覆盖）：

- **向量库 / RAG**：`tools/semantic_search.py` 基于 **Chroma**（`PersistentClient`）存储代码分块向量到 `.cache/chroma/`，按项目路径生成独立 collection，按文件 MD5 做增量更新。若未安装 `chromadb`，自动回退到内存 numpy 检索。
- **会话记忆**：`agent/graph.py` 使用 **LangGraph SqliteSaver**，会话状态持久化到 `.cache/checkpoints.sqlite`，按 `thread_id` 跨进程恢复。依赖缺失时回退 `MemorySaver`（不持久化）。
- **嵌入模型**：默认调用在线 Embedding API（OpenAI 兼容），通过 `ACTIVE_EMBEDDING="local"` 可切换到本地 `sentence-transformers` 兜底。

## 使用

```bash
python3 dev_agent.py
```

交互命令：

| 命令 | 说明 |
|------|------|
| `/analyze <项目路径>` | 分析项目结构 |
| `/develop <需求描述>` | 进入结构化开发流程 |
| `/review <文件路径或代码>` | 代码审查 |
| `/python <代码>` | 执行 Python 代码 |
| `/java <代码>` | 编译运行 Java 代码 |
| `/lang <语言>` | 切换语言上下文 |
| `/project` | 查看当前项目和语言 |
| `/clear` | 清空对话历史 |
| `/help` | 显示帮助 |
| `/exit` | 退出 |

示例：

```text
You> /analyze /path/to/project
You> /develop 给这个项目添加一个 health_check() 函数
You> 总结 https://example.com 的页面内容
```

## Web 界面

除命令行 REPL 外，提供基于 FastAPI + 原生前端的 Web 界面，复用同一套状态图并以 SSE 流式展示每个节点的执行过程。

安装（uvicorn 已随 chromadb 引入，只需补 fastapi）：

```bash
pip install fastapi uvicorn
```

启动：

```bash
python web/server.py
# 或
uvicorn web.server:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。界面支持：任务模式选择（自动/analyze/develop/review/chat）、语言、项目路径、新会话，以及实时的「执行过程」节点流。

点击右上角 **⚙ 设置** 可直接在界面配置 `DEEPSEEK_API_KEY`（或 GLM）的 API Key：保存后立即对后续对话生效，并持久化到 `.cache/secrets.json`（已被 `.gitignore` 忽略），重启后自动加载。密钥在界面只以脱敏形式回显，接口不返回明文。密钥优先级为 `secrets.json > 环境变量 > 默认占位`。

可用环境变量 `CODE_AGENT_WEB_HOST` / `CODE_AGENT_WEB_PORT` 调整监听地址。

> 安全提示：Agent 具备读写文件、执行 Python/Java 代码的能力，Web 服务**默认仅绑定 `127.0.0.1` 且无鉴权**，请勿在未加认证的情况下暴露到公网或局域网。

## Skill 插件

在 `skills/` 下创建子目录即可扩展能力：

```text
skills/
└── my_skill/
    ├── manifest.json
    └── __init__.py
```

Skill 模块可导出：

- `get_tools()`：返回 LangChain tools。
- `get_hooks()`：返回安全检查 hooks。
- `get_skill_prompt()`：返回注入到 Agent 的能力说明。
- `configure(config)`：可选，接收外部配置。

内置 `web_reader` 示例提供 `read_webpage` 工具，用于读取静态网页正文。对于 SPA 或强动态渲染网站，会提示无法通过普通 HTTP 请求获取动态内容。

## 评估

运行全部用例：

```bash
python3 eval_harness.py
```

运行指定用例：

```bash
python3 eval_harness.py --case develop_plan_01
```

## 技术栈

- **LangGraph**：状态图编排 + SqliteSaver 会话持久化。
- **LangChain**：消息类型、工具绑定、LLM 抽象、Embedding 抽象。
- **Pydantic**：结构化输出 schema 与校验。
- **Chroma**：持久化向量库，承载 RAG 代码语义检索。
- **sentence-transformers**：本地嵌入兜底（可选）。
- **Requests**：网页读取和 HTTP 调用。

## License

MIT
