# -*- coding: utf-8 -*-
"""
LangGraph 核心状态图 - 将 chat_loop 重构为显式状态机
节点: classify → explore → architect → implement → verify → review → report
支持条件路由、并行审查、检查点持久化、Human-in-the-loop
"""
import json
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from state import AgentState, TaskClassification, ExplorationResult, DesignResult, ReviewResult
from llm import get_llm, get_structured_llm
from tools_langchain import get_all_tools, get_all_tool_map
from config import MODEL
from agents import get_agent_prompt
from lang_skills import get_skill
from skill_loader import load_all_skills, get_all_skill_prompts

# 启动时加载所有外部 skill（无 skill 时为空，可按需在 skills/ 下添加）
load_all_skills()

# 动态获取所有工具（核心 + skill）
LANGCHAIN_TOOLS = get_all_tools()
LANGCHAIN_TOOL_MAP = get_all_tool_map()


def _build_skill_hint(language: str) -> str:
    """构建完整的技能提示：语言技能 + 外部 skill 提示"""
    parts = []
    if language:
        lang_skill = get_skill(language)
        if lang_skill:
            parts.append(f"## 语言技能参考\n{lang_skill}")
    skill_prompts = get_all_skill_prompts()
    if skill_prompts:
        parts.append(f"## 外部技能参考\n{skill_prompts}")
    return "\n\n".join(parts)


# ============ 系统提示 ============

SYSTEM_PROMPT = """你是一个专业的多语言程序开发智能体（Dev Agent），精通 Python、Spark SQL、Java 的项目分析与开发。

## 核心能力
1. 项目扫描: 识别项目结构、语言、框架、构建工具
2. 代码阅读: 读取源码文件，理解代码逻辑
3. 代码搜索: 正则搜索代码，快速定位关键代码
4. Python执行: 在沙箱中执行Python代码，验证逻辑
5. SQL执行: 通过Bigda API执行Spark SQL查询
6. Java执行: 编译运行Java代码片段
7. 项目分析: Python/Java项目深度分析（入口点、依赖、架构）
8. SQL分析: 语法检查、表血缘、字段映射
9. 代码审查: 多维度审查，置信度过滤
10. 文件写入: 创建新文件或修改代码（带安全检查）

## 工作流程

### 分析任务
1. scan_project 了解项目结构
2. read_file / search_code 深入理解代码
3. analyze_python / analyze_java / analyze_sql 针对性分析
4. 给出分析结论和建议

### 开发任务
1. scan_project 了解项目结构
2. read_file 阅读相关代码
3. 设计方案（如复杂任务可考虑多方案对比）
4. write_file 写入代码（带安全确认）
5. execute_python / execute_sql / execute_java 验证代码
6. code_review 审查代码质量

### 审查任务
1. read_file 读取待审查代码
2. code_review 规则扫描 + 深度分析
3. 汇总审查结果（仅报告置信度>=80的问题）

### SQL查询任务
（SQL查询工作流由外部 skill 动态注入，参见运行时 skill_prompt）
5. 向用户解读查询结果

## 安全规则
- 执行代码前会自动进行安全检查，拦截危险操作
- 写文件前会确认大文件写入
- SQL仅允许SELECT查询，禁止DDL/DML
- 如遇到 [需确认] 提示，需要用户明确确认后才能继续

## 注意事项
- 先理解再动手：用 scan_project + read_file 充分了解项目后再修改
- 分步执行：复杂任务拆分为小步骤，每步验证
- 遵循现有代码风格和约定

## 严格工具调用规则
- **禁止编造工具结果**：凡是涉及文件读取、代码执行、SQL查询、项目扫描等操作，必须调用对应工具获取真实结果，严禁凭想象编造执行结果
- **验证必须真实执行**：当任务要求"验证"、"测试"、"执行看看结果"时，必须调用 execute_python / execute_sql / execute_java 工具实际运行代码，不能仅给出理论分析就声称"验证通过"
- **工具调用优先于推断**：能用工具获取的信息不要靠推断，例如文件内容用 read_file 读取而非猜测
- **结果引用真实数据**：回复中引用的执行结果、输出、报错等必须是工具真实返回的，不能虚构
- SQL中使用 '${date:y-m-d}' 表示带-日期，'${date:ymd}' 表示不带-日期
"""


# ============ 工具调用辅助 ============

def _run_tool_loop(llm_with_tools, messages, max_iterations=10):
    """通用工具调用循环，返回最终 AI 消息文本、所有中间信息、完整对话历史

    增加一致性检查：如果 LLM 声称验证/执行了代码但没有调用对应工具，
    追加提示强制其真实调用工具。
    """
    all_tool_results = []
    # 需要真实执行工具的关键词
    VERIFY_KEYWORDS = ["验证", "测试", "执行", "运行", "结果", "输出", "通过", "pass"]
    EXEC_TOOLS = {"execute_python", "execute_sql", "execute_java"}

    for iteration in range(max_iterations):
        # 修复消息兼容性：部分 API（如 GLM）不接受空 content 的消息
        valid_messages = []
        for m in messages:
            if isinstance(m, AIMessage) and m.tool_calls and not m.content:
                # GLM 要求 AIMessage 的 content 不能为空，补充占位文本
                m = AIMessage(content="[调用工具]", tool_calls=m.tool_calls)
            elif isinstance(m, (HumanMessage, AIMessage)) and not getattr(m, 'content', None) and not getattr(m, 'tool_calls', None):
                # 跳过既无内容又无工具调用的消息
                continue
            valid_messages.append(m)
        response = llm_with_tools.invoke(valid_messages)
        messages.append(response)

        if not response.tool_calls:
            final_text = response.content or ""

            # 一致性检查：如果回复暗示已执行验证但实际没调用执行类工具，追加固化提示
            if final_text and not any(tr["tool"] in EXEC_TOOLS for tr in all_tool_results):
                # 检查是否暗示了验证/执行
                hint_verify = any(kw in final_text for kw in VERIFY_KEYWORDS)
                if hint_verify:
                    # 追加提示，让 LLM 真正调用工具
                    messages.append(HumanMessage(content=(
                        "你刚才的回复中提到了验证/执行/测试结果，但并没有实际调用 execute_python/execute_sql/execute_java 工具。"
                        "请务必调用对应工具真实执行代码，获取真实结果后再回答。不要编造执行结果。"
                    )))
                    continue  # 继续循环，让 LLM 重新回复

            return final_text, all_tool_results, messages

        for tc in response.tool_calls:
            tool_fn = LANGCHAIN_TOOL_MAP.get(tc["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tc["args"])
                    all_tool_results.append({
                        "tool": tc["name"],
                        "args": tc["args"],
                        "result": str(result)[:500],
                    })
                    messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
                except Exception as e:
                    all_tool_results.append({
                        "tool": tc["name"],
                        "args": tc["args"],
                        "result": f"异常: {str(e)}",
                    })
                    messages.append(ToolMessage(content=f"工具执行异常: {str(e)}", tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"]))

    return "", all_tool_results, messages


# ============ 图节点函数 ============

def classify_task(state: AgentState) -> dict:
    """节点: 分类任务类型和语言

    如果入口已指定 task_type（通过 /analyze /develop /review 命令），
    则跳过 LLM 分类，直接使用指定值。仅对未指定类型时才用 LLM 判断。
    """
    existing_type = state.get("task_type", "")
    existing_lang = state.get("language", "")

    # 已有明确分类，跳过 LLM
    if existing_type in ("analyze", "develop", "review"):
        return {
            "task_type": existing_type,
            "language": existing_lang,
            "messages": [AIMessage(content=f"[分类] 任务类型: {existing_type}, 语言: {existing_lang} (命令指定)")],
        }

    # 无明确分类，用 LLM 判断
    user_input = state.get("user_input", "")
    # 如果 user_input 为空，从 messages 中提取
    if not user_input:
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage) and msg.content:
                user_input = msg.content
                break

    classify_llm = get_structured_llm(TaskClassification, temperature=0)
    result = classify_llm.invoke([
        SystemMessage(content=(
            "你是一个任务分类器。根据用户输入判断任务类型和编程语言。\n\n"
            "分类规则:\n"
            "- analyze: 用户要求分析项目结构、了解代码架构、识别技术栈\n"
            "- develop: 用户要求写代码、实现功能、开发新特性\n"
            "- review: 用户要求审查代码质量、找bug、代码review\n"
            "- chat: 其他所有对话，包括知识问答、解释概念、SQL优化建议等\n\n"
            "注意: 知识问答类（如'如何优化SQL'、'Python和Java区别'）应归类为 chat，不是 analyze。"
        )),
        HumanMessage(content=user_input),
    ])

    return {
        "task_type": result.task_type,
        "language": result.language or existing_lang,
        "user_input": user_input,
        "messages": [AIMessage(content=f"[分类] 任务类型: {result.task_type}, 语言: {result.language}, 置信度: {result.confidence}%")],
    }


def route_by_task(state: AgentState) -> str:
    """条件路由: 根据任务类型决定路径"""
    task_type = state.get("task_type", "chat")
    if task_type == "analyze":
        return "explore"
    elif task_type == "develop":
        return "explore"
    elif task_type == "review":
        return "review"
    else:
        return "chat_respond"


def explore_project(state: AgentState) -> dict:
    """节点: 探索项目结构"""
    user_input = state.get("user_input", "")
    language = state.get("language", "")
    # 如果 user_input 为空，从 messages 中提取
    if not user_input:
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage) and msg.content:
                user_input = msg.content
                break

    skill_hint = _build_skill_hint(language) if language else ""

    explore_prompt = get_agent_prompt("code-explorer", language)

    llm = get_llm()
    llm_with_tools = llm.bind_tools(LANGCHAIN_TOOLS)

    messages = [
        SystemMessage(content=explore_prompt + skill_hint),
        HumanMessage(content=user_input),
    ]

    exploration_text, _, _ = _run_tool_loop(llm_with_tools, messages, max_iterations=10)

    # 尝试结构化输出
    try:
        structured_llm = get_structured_llm(ExplorationResult, temperature=0)
        exploration_result = structured_llm.invoke([
            SystemMessage(content="根据以下探索结果，提取结构化信息。"),
            HumanMessage(content=exploration_text or user_input),
        ])
        exploration_dict = exploration_result.model_dump()
    except Exception:
        exploration_dict = {
            "language": language or "unknown",
            "framework": "",
            "build_tool": "",
            "entry_points": [],
            "key_files": [],
            "patterns": [],
            "observations": [],
            "summary": exploration_text[:1000] if exploration_text else "探索完成",
        }

    return {
        "exploration_result": exploration_dict,
        "messages": [AIMessage(content=f"[探索完成] {exploration_dict.get('summary', '')}")],
    }


def generate_report(state: AgentState) -> dict:
    """节点: 生成分析报告（analyze 路径终点）

    使用 LLM 生成丰富、可读的分析报告，包含架构可视化和依赖统计
    """
    exploration = state.get("exploration_result", {})
    user_input = state.get("user_input", "")
    language = state.get("language", "")

    if not exploration:
        return {"final_output": "未能完成项目探索。", "messages": []}

    # 用 LLM 生成丰富报告
    llm = get_llm(temperature=0.3)
    report_prompt = f"""根据以下项目探索数据，生成一份详细的项目分析报告。

要求:
1. 包含项目概览（语言、框架、构建工具）
2. 包含架构分层图（用文本框图表示）
3. 包含入口点分析（文件:行号 + 类型）
4. 包含依赖统计（Top 10 外部依赖引用次数）
5. 包含设计模式/约定识别
6. 包含优缺点观察和改进建议

项目探索数据:
{json.dumps(exploration, ensure_ascii=False, indent=2)}

用户原始问题: {user_input}
"""

    response = llm.invoke([
        SystemMessage(content="你是一个专业的项目分析报告撰写者。生成结构清晰、内容丰富的Markdown格式报告。"),
        HumanMessage(content=report_prompt),
    ])

    report = response.content or ""

    return {
        "final_output": report,
        "messages": [AIMessage(content=report)],
    }


def design_solutions(state: AgentState) -> dict:
    """节点: 设计多方案架构（develop 路径）"""
    user_input = state.get("user_input", "")
    language = state.get("language", "")
    exploration = state.get("exploration_result", {})

    architect_prompt = get_agent_prompt("code-architect", language)

    context = f"用户需求: {user_input}\n\n项目信息: {json.dumps(exploration, ensure_ascii=False, indent=2) if exploration else '无'}"

    try:
        structured_llm = get_structured_llm(DesignResult, temperature=0.3)
        design_result = structured_llm.invoke([
            SystemMessage(content=architect_prompt),
            HumanMessage(content=context),
        ])
        design_dict = design_result.model_dump()
    except Exception:
        llm = get_llm(temperature=0.3)
        response = llm.invoke([
            SystemMessage(content=architect_prompt),
            HumanMessage(content=context),
        ])
        design_dict = {
            "options": [{"name": "默认方案", "approach": response.content[:500], "complexity": "中等"}],
            "recommended": 0,
            "reason": "自动选择",
        }

    options_text = ""
    for i, opt in enumerate(design_dict.get("options", [])):
        options_text += f"\n### 方案{i+1}: {opt.get('name', '')}\n"
        options_text += f"理念: {opt.get('approach', '')}\n"
        options_text += f"复杂度: {opt.get('complexity', '')}\n"
        if opt.get('pros'):
            options_text += f"优点: {', '.join(opt['pros'])}\n"
        if opt.get('cons'):
            options_text += f"缺点: {', '.join(opt['cons'])}\n"

    return {
        "design_options": design_dict.get("options", []),
        "chosen_design_index": design_dict.get("recommended", 0),
        "messages": [AIMessage(content=f"[设计方案]{options_text}\n推荐方案{design_dict.get('recommended', 0)+1}: {design_dict.get('reason', '')}")],
    }


def implement_code(state: AgentState) -> dict:
    """节点: 实现代码（develop 路径）"""
    user_input = state.get("user_input", "")
    language = state.get("language", "")
    design_options = state.get("design_options", [])
    chosen_index = state.get("chosen_design_index", 0)
    exploration = state.get("exploration_result", {})
    iteration = state.get("iteration", 0)
    prev_error = state.get("implementation_error")

    chosen = design_options[chosen_index] if design_options and chosen_index < len(design_options) else {}

    impl_prompt = f"用户需求: {user_input}\n"
    impl_prompt += f"选择方案: {chosen.get('name', '默认方案')}\n"
    impl_prompt += f"方案详情: {json.dumps(chosen, ensure_ascii=False)}\n"
    if exploration:
        impl_prompt += f"项目上下文: {json.dumps(exploration, ensure_ascii=False)[:2000]}\n"
    if prev_error:
        impl_prompt += f"\n上一轮实现错误: {prev_error}\n请修复此问题。\n"

    llm = get_llm()
    llm_with_tools = llm.bind_tools(LANGCHAIN_TOOLS)

    skill_hint = _build_skill_hint(language) if language else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT + skill_hint),
        HumanMessage(content=impl_prompt),
    ]

    # 工具调用循环
    max_iterations = 12
    implementation_text = ""
    files_written = []
    execution_results = []

    for _ in range(max_iterations):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            implementation_text = response.content or ""
            break

        for tc in response.tool_calls:
            tool_fn = LANGCHAIN_TOOL_MAP.get(tc["name"])
            if tool_fn:
                try:
                    result = tool_fn.invoke(tc["args"])
                    if tc["name"] == "write_file":
                        files_written.append(tc["args"].get("file_path", ""))
                    elif tc["name"] in ("execute_python", "execute_java", "execute_sql"):
                        execution_results.append(f"[{tc['name']}] {str(result)[:300]}")
                    messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
                except Exception as e:
                    messages.append(ToolMessage(content=f"工具执行异常: {str(e)}", tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"]))

    return {
        "implementation": {
            "description": implementation_text[:2000],
            "files_written": files_written,
            "execution_results": execution_results,
        },
        "implementation_error": None,
        "iteration": iteration + 1,
        "messages": [AIMessage(content=f"[实现完成] {implementation_text[:500]}")],
    }


def verify_result(state: AgentState) -> dict:
    """节点: 验证实现结果"""
    implementation = state.get("implementation", {})
    user_input = state.get("user_input", "")

    execution_results = implementation.get("execution_results", [])
    files_written = implementation.get("files_written", [])

    has_error = False
    error_msg = ""
    for result in execution_results:
        if "错误" in result or "失败" in result or "退出码: 1" in result:
            has_error = True
            error_msg += result + "\n"

    if has_error:
        return {
            "implementation_error": error_msg,
            "verify_result": {"passed": False, "error": error_msg},
            "messages": [AIMessage(content=f"[验证失败] {error_msg[:300]}")],
        }

    llm = get_llm()
    verify_prompt = f"""验证以下实现是否满足用户需求。

用户需求: {user_input}

已写入文件: {', '.join(files_written) if files_written else '无'}

执行结果:
{chr(10).join(execution_results) if execution_results else '无执行结果'}

请判断实现是否正确。如果正确回复 YES，否则回复 NO 并说明原因。"""

    response = llm.invoke([HumanMessage(content=verify_prompt)])
    passed = "YES" in (response.content or "").upper()[:10]

    verify_dict = {"passed": passed}
    if not passed:
        verify_dict["error"] = response.content or ""

    return {
        "implementation_error": None if passed else response.content,
        "verify_result": verify_dict,
        "messages": [AIMessage(content=f"[验证{'通过' if passed else '失败'}]")],
    }


def should_retry(state: AgentState) -> str:
    """条件路由: 判断是否需要重试实现"""
    iteration = state.get("iteration", 0)
    impl_error = state.get("implementation_error")

    if impl_error and iteration < 3:
        return "architect"
    return "review"


def review_code(state: AgentState) -> dict:
    """节点: 代码审查（三维度并行，输出完整修复代码示例）"""
    user_input = state.get("user_input", "")
    language = state.get("language", "python")
    implementation = state.get("implementation", {})

    # 获取待审查代码
    code_to_review = ""
    files_written = implementation.get("files_written", []) if implementation else []

    if files_written:
        from tools import tool_read_file
        code_parts = []
        for fp in files_written[:5]:
            try:
                content = tool_read_file({"file_path": fp})
                code_parts.append(f"--- {fp} ---\n{content}")
            except Exception:
                pass
        code_to_review = "\n\n".join(code_parts)
    elif implementation and implementation.get("description"):
        code_to_review = implementation["description"]
    else:
        # review 路径：使用带工具的 LLM 读取代码
        llm = get_llm()
        llm_with_tools = llm.bind_tools(LANGCHAIN_TOOLS)

        review_prompt = get_agent_prompt("code-reviewer", language)
        skill_hint = _build_skill_hint(language)

        messages = [
            SystemMessage(content=review_prompt + skill_hint),
            HumanMessage(content=user_input),
        ]

        code_to_review, _, _ = _run_tool_loop(llm_with_tools, messages, max_iterations=6)

    if not code_to_review:
        return {
            "review_issues": [],
            "final_output": "审查完成：无代码可审查。",
            "messages": [AIMessage(content="审查完成：无代码可审查。")],
        }

    # 用 LLM 生成完整审查报告（含修复代码示例）
    llm = get_llm(temperature=0)
    review_report_prompt = f"""你是资深代码审查专家。请对以下 {language} 代码进行全面审查。

## 审查维度
1. **简洁性/DRY/优雅性**: 重复代码、命名、函数拆分、过度工程
2. **Bug/正确性**: 边界条件、空值检查、异常处理、并发安全、资源泄漏
3. **规范/约定**: 编码规范、语言最佳实践、日志、配置管理

## 输出要求
- 每个问题附带：严重等级(CRITICAL/IMPORTANT/MINOR)、置信度(0-100)、文件位置、问题描述
- 仅报告置信度>=80的问题
- 每个问题必须附带**完整的修复代码示例**，而非仅简短建议
- 最后给出总体评价和代码质量评分(0-100)
- 如果代码可整体改进，给出重构后的完整代码

## 待审查代码
{code_to_review[:4000]}
"""

    response = llm.invoke([
        SystemMessage(content="你是代码审查专家，输出Markdown格式审查报告，每个问题必须附带完整修复代码。"),
        HumanMessage(content=review_report_prompt),
    ])

    report = response.content or "审查完成。"

    # 同时做结构化审查以获取 issues 数据
    all_issues = []
    dimensions = ["简洁性/DRY/优雅性", "Bug/正确性", "规范/约定"]
    review_llm = get_structured_llm(ReviewResult, temperature=0)

    for dim in dimensions:
        try:
            result = review_llm.invoke([
                SystemMessage(content=f"你是代码审查专家，专注于{dim}维度。仅报告置信度>=80的问题。"),
                HumanMessage(content=f"请审查以下{language}代码:\n\n{code_to_review[:3000]}"),
            ])
            all_issues.extend([issue.model_dump() for issue in result.issues])
        except Exception:
            from tools import tool_code_review
            tool_code_review({"code": code_to_review[:3000], "language": language})

    return {
        "review_issues": all_issues,
        "final_output": report,
        "messages": [AIMessage(content=report)],
    }


def chat_respond(state: AgentState) -> dict:
    """节点: 普通对话（非结构化任务）

    直接用 LLM + 工具回答，不走 explore→report 路径
    如果工具循环后没有文本输出，用 LLM 做最终总结
    保存完整对话历史到 state.messages，确保跨轮上下文可追溯
    """
    user_input = state.get("user_input", "")
    language = state.get("language", "")
    # 如果 user_input 为空，从 messages 中提取
    if not user_input:
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage) and msg.content:
                user_input = msg.content
                break

    skill_hint = _build_skill_hint(language) if language else ""

    llm = get_llm()
    llm_with_tools = llm.bind_tools(LANGCHAIN_TOOLS)

    # 携带历史 messages（来自之前的轮次）
    existing_messages = state.get("messages", [])
    # 过滤：只保留 HumanMessage 和有内容的 AIMessage
    # ToolMessage 不能单独发给 API（需要配对的 tool_calls），所以转换为文本摘要
    history = []
    for msg in existing_messages:
        if hasattr(msg, 'content') and msg.content:
            if isinstance(msg, HumanMessage):
                history.append(HumanMessage(content=msg.content[:2000]))
            elif isinstance(msg, AIMessage):
                history.append(AIMessage(content=msg.content[:1000]))
            elif isinstance(msg, ToolMessage):
                # ToolMessage 转换为 AIMessage 摘要，避免 API 报错
                history.append(AIMessage(content=f"[工具结果] {msg.content[:500]}"))

    messages = [SystemMessage(content=SYSTEM_PROMPT + skill_hint)]
    # 如果有历史对话，加入上下文（但限制长度避免 token 超限）
    if history:
        # 只保留最近 20 条有内容的消息作为上下文
        recent_history = history[-20:]
        messages.extend(recent_history)
    messages.append(HumanMessage(content=user_input))

    final_text, tool_results, full_history = _run_tool_loop(llm_with_tools, messages, max_iterations=10)

    # 降级：工具循环后没有文本输出，用 LLM 总结工具结果
    if not final_text and tool_results:
        summary_prompt = "根据以下工具执行结果，回答用户的问题。\n\n"
        for tr in tool_results:
            summary_prompt += f"工具 {tr['tool']}({json.dumps(tr['args'], ensure_ascii=False)[:100]}):\n{tr['result'][:500]}\n\n"
        summary_prompt += f"\n用户问题: {user_input}\n\n请直接给出答案。"

        summary_response = llm.invoke([HumanMessage(content=summary_prompt)])
        final_text = summary_response.content or ""

    # 保存完整对话历史（含工具调用细节），确保后续轮次可追溯
    # 转换为可序列化的消息列表：只保留 Human/AI/Tool 三种类型的消息
    saved_messages = []
    for msg in full_history:
        if isinstance(msg, HumanMessage):
            saved_messages.append(HumanMessage(content=msg.content[:2000]))
        elif isinstance(msg, AIMessage):
            # AI 消息：保存文本内容，如果有 tool_calls 也保存摘要
            if msg.content:
                saved_messages.append(AIMessage(content=msg.content[:1000]))
            elif msg.tool_calls:
                # 工具调用：记录调用了什么工具和参数
                tc_summary = "; ".join(
                    f"{tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:100]})"
                    for tc in msg.tool_calls
                )
                saved_messages.append(AIMessage(content=f"[调用工具: {tc_summary}]"))
        elif isinstance(msg, ToolMessage):
            saved_messages.append(ToolMessage(content=msg.content[:500], tool_call_id=msg.tool_call_id))

    return {
        "final_output": final_text,
        "messages": saved_messages,
    }


# ============ 构建图 ============

def build_graph():
    """构建 LangGraph 状态图"""
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("classify", classify_task)
    graph.add_node("explore", explore_project)
    graph.add_node("architect", design_solutions)
    graph.add_node("implement", implement_code)
    graph.add_node("verify", verify_result)
    graph.add_node("review", review_code)
    graph.add_node("report", generate_report)
    graph.add_node("chat_respond", chat_respond)

    # 设置入口
    graph.set_entry_point("classify")

    # 条件路由：classify → 不同路径
    graph.add_conditional_edges("classify", route_by_task, {
        "explore": "explore",
        "review": "review",
        "chat_respond": "chat_respond",
    })

    # analyze 路径: explore → report → END
    graph.add_conditional_edges("explore", lambda s: "report" if s.get("task_type") == "analyze" else "architect", {
        "report": "report",
        "architect": "architect",
    })
    graph.add_edge("report", END)

    # develop 路径: architect → implement → verify → (retry | review) → END
    graph.add_edge("architect", "implement")
    graph.add_edge("implement", "verify")
    graph.add_conditional_edges("verify", should_retry, {
        "architect": "architect",
        "review": "review",
    })
    graph.add_edge("review", END)

    # chat 路径
    graph.add_edge("chat_respond", END)

    # 编译图（带检查点）
    return graph.compile(checkpointer=MemorySaver())
