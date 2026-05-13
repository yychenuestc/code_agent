# Code Agent

基于 LangGraph 状态机的多语言程序开发智能体，支持项目分析、代码开发、代码审查和对话问答。

## 特性

- **多模型适配**：支持 DeepSeek / GLM 等多种 OpenAI 兼容 API，配置切换即可
- **LangGraph 状态机驱动**：任务自动分类路由到不同处理流程（分析/开发/审查/对话）
- **16 个核心工具**：项目扫描、文件读写、精确编辑、代码搜索、语义搜索、Python/Java 执行、Git 工作流、代码审查等
- **Skill 插件体系**：通过 `skills/` 目录扩展能力
- **安全拦截层**：Hook 系统自动拦截危险操作（文件删除、代码注入等）
- **上下文记忆**：跨轮次对话保持完整上下文，支持工具调用历史追溯
- **工具调用一致性校验**：防止 LLM 编造工具执行结果，强制真实调用验证
- **模块化架构**：按功能域拆分为 core/tools/agent 三层包结构

## 项目结构

```
code_agent/
├── dev_agent.py              # 主入口，交互式 REPL
├── eval_harness.py           # 评估框架
├── core/                     # 核心基础设施
│   ├── config.py             # 配置文件（API Key、超时、安全规则）
│   ├── state.py              # AgentState 定义 + Pydantic 结构化输出模型
│   ├── hooks.py              # Hook 安全拦截器
│   └── llm.py                # LLM 封装（多模型适配、结构化输出）
├── tools/                    # 工具包
│   ├── __init__.py           # 聚合 TOOLS + TOOL_DISPATCH
│   ├── file_ops.py           # scan_project, read_file, write_file, edit_file
│   ├── search.py             # search_code, semantic_search
│   ├── execution.py          # execute_python, execute_java
│   ├── analysis.py           # analyze_python/java/sql, code_review
│   ├── git_ops.py            # git_status/diff/commit/checkout
│   ├── langchain_adapter.py  # LangChain @tool 适配层 + 并行执行
│   └── semantic_search.py    # 语义代码搜索引擎（RAG）
├── agent/                    # Agent 逻辑
│   ├── graph.py              # LangGraph 核心状态图（8 个节点）
│   ├── agents.py             # 专职 Agent 定义（explorer/architect/reviewer）
│   ├── lang_skills.py        # 语言技能提示（Python/SQL/Java）
│   └── skill_loader.py       # Skill 插件自动发现与加载
├── skills/                   # 外部 Skill 插件目录
│   └── __init__.py
└── .gitignore
```

## 状态图流程

```
                    ┌──────────┐
                    │ classify │
                    └────┬─────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    ┌─────▼─────┐  ┌────▼────┐  ┌──────▼──────┐
    │  explore  │  │  review │  │chat_respond │
    └─────┬─────┘  └────┬────┘  └──────┬──────┘
          │              │              │
   ┌──────┴──────┐       │            END
   │             │       │
┌──▼───┐  ┌─────▼────┐  │
│report│  │ architect │  │
└──┬───┘  └─────┬────┘  │
   │            │        │
   │      ┌─────▼─────┐  │
   │      │ implement │  │
   │      └─────┬─────┘  │
   │            │        │
   │      ┌─────▼─────┐  │
   │      │  verify   │──┘ (retry → architect)
   │      └─────┬─────┘
   │            │
   │      ┌─────▼─────┐
   │      │  review   │
   │      └─────┬─────┘
   │            │
   END          END
```

- **classify**：自动分类任务类型（analyze/develop/review/chat）
- **explore**：扫描项目、搜索代码，收集信息
- **architect**：设计解决方案，支持多方案对比
- **implement**：写代码实现，带安全确认
- **verify**：执行验证，失败可回退到 architect 重试
- **review**：代码审查，置信度 >= 80% 才报告
- **report**：生成分析报告
- **chat_respond**：对话模式，支持工具调用循环

## 核心工具

| 分类 | 工具 | 说明 |
|------|------|------|
| 文件操作 | `scan_project` | 扫描项目目录结构，识别语言/框架 |
| | `read_file` | 读取文件内容 |
| | `write_file` | 写入/创建文件（带安全检查） |
| | `edit_file` | 精确编辑已有文件（行范围/文本/函数替换） |
| 代码搜索 | `search_code` | 正则搜索代码 |
| | `semantic_search` | 语义代码搜索，用自然语言描述即可找到相关代码 |
| 代码执行 | `execute_python` | 执行 Python 代码（沙箱 + 超时） |
| | `execute_java` | 编译运行 Java 代码 |
| 项目分析 | `analyze_python` | 深入分析 Python 项目 |
| | `analyze_java` | 深入分析 Java 项目 |
| | `analyze_sql` | 分析 SQL 脚本 |
| | `code_review` | 代码审查（简洁性/正确性/规范性） |
| Git 工作流 | `git_status` | 查看 Git 仓库状态 |
| | `git_diff` | 查看 Git 差异 |
| | `git_commit` | 提交 Git 变更 |
| | `git_checkout` | 切换分支/创建分支/恢复文件 |

## 安装

```bash
pip install langchain-core langchain-openai langgraph requests sentence-transformers
```

## 配置

编辑 `core/config.py`，修改 `ACTIVE_MODEL` 选择模型，并填入对应的 API Key：

```python
MODEL_CONFIGS = {
    "deepseek": {
        "api_key": "your-deepseek-api-key",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "glm": {
        "api_key": "your-zhipu-api-key",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.1",
    },
}

# 切换模型：修改此值即可
ACTIVE_MODEL = "deepseek"  # 或 "glm"
```

也支持添加其他 OpenAI 兼容 API（如 OpenAI、Azure OpenAI 等），按上述格式在 `MODEL_CONFIGS` 中新增预设即可。

## 使用

```bash
python3 dev_agent.py
```

### 交互命令

| 命令 | 说明 |
|------|------|
| `/analyze <项目路径>` | 分析项目结构 |
| `/develop <需求描述>` | 结构化开发流程 |
| `/review <文件路径>` | 代码审查 |
| `/python <代码>` | 执行 Python 代码 |
| `/java <代码>` | 编译运行 Java 代码 |
| `/lang <语言>` | 切换语言上下文 (python/sql/java) |
| `/project` | 查看当前项目和语言 |
| `/clear` | 清空对话历史 |
| `/help` | 显示帮助 |
| `/exit` | 退出 |

### 示例对话

```
You> 用Python实现一个LRU Cache，支持get和put操作，时间复杂度O(1)
  [classify] 任务类型: chat
  [chat_respond] 我来实现一个LRU Cache...
  （自动调用 execute_python 验证）

You> /analyze /path/to/project
  [classify] 任务类型: analyze
  [explore] 扫描项目结构...
  [report] 生成分析报告

You> 这段代码有什么性能问题？def fib(n): return fib(n-1) + fib(n-2)
  [classify] 任务类型: chat
  [chat_respond] 分析性能问题并给出优化版本...
```

## Skill 插件

在 `skills/` 目录下创建子目录即可扩展 Agent 能力：

```
skills/
└── my_skill/
    ├── manifest.json    # 元信息和配置
    └── __init__.py      # 实现，需导出 get_tools(), get_hooks(), get_skill_prompt()
```

`agent/skill_loader.py` 会自动发现并加载所有 skill，其工具和提示会动态注入到 Agent 中。

## 技术栈

- **LangGraph** — 状态图引擎，将 Agent 从 while 循环重构为显式状态机
- **LangChain** — LLM 抽象层、工具绑定、消息类型
- **DeepSeek / GLM 等** — OpenAI 兼容的 LLM 后端，配置切换
- **sentence-transformers** — 语义代码搜索的嵌入模型
- **Pydantic** — 结构化输出 schema

## License

MIT
