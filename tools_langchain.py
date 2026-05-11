# -*- coding: utf-8 -*-
"""
LangChain Tool 适配层 - 将核心 tools.py 的工具函数封装为 LangChain Tool
SQL 查询工具由外部 skill 提供，不在此文件中
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.tools import tool

from tools import (
    tool_scan_project,
    tool_read_file,
    tool_write_file,
    tool_edit_file,
    tool_search_code,
    tool_execute_python,
    tool_execute_java,
    tool_analyze_python,
    tool_analyze_java,
    tool_analyze_sql,
    tool_code_review,
    tool_git_status,
    tool_git_diff,
    tool_git_commit,
    tool_git_checkout,
    tool_semantic_search,
)


@tool
def scan_project(project_path: str, depth: int = 3) -> str:
    """扫描项目目录结构，识别编程语言、框架、构建工具。输入项目根目录路径，返回项目概览信息。"""
    return tool_scan_project({"project_path": project_path, "depth": depth})


@tool
def read_file(file_path: str, start_line: int = 1, end_line: int = 0) -> str:
    """读取指定文件的内容。支持查看源码、配置文件等。end_line为0表示读到文件末尾。"""
    args = {"file_path": file_path, "start_line": start_line}
    if end_line > 0:
        args["end_line"] = end_line
    return tool_read_file(args)


@tool
def write_file(file_path: str, content: str) -> str:
    """写入或创建文件。对破坏性操作会进行安全检查。用于创建新文件或覆盖已有文件。"""
    return tool_write_file({"file_path": file_path, "content": content})


@tool
def edit_file(file_path: str, mode: str, start_line: int = 0, end_line: int = 0,
              old_text: str = "", new_text: str = "", function_name: str = "",
              new_code: str = "", class_name: str = "") -> str:
    """精确编辑已有文件。支持三种模式: line_range(替换行范围), replace(文本替换), function_replace(替换函数定义)。"""
    args = {"file_path": file_path, "mode": mode}
    if start_line:
        args["start_line"] = start_line
    if end_line:
        args["end_line"] = end_line
    if old_text:
        args["old_text"] = old_text
    if new_text:
        args["new_text"] = new_text
    if function_name:
        args["function_name"] = function_name
    if new_code:
        args["new_code"] = new_code
    if class_name:
        args["class_name"] = class_name
    return tool_edit_file(args)


@tool
def search_code(project_path: str, pattern: str, file_glob: str = "") -> str:
    """在项目中搜索代码内容。支持正则表达式。用于查找函数定义、类引用、配置项等。"""
    return tool_search_code({
        "project_path": project_path,
        "pattern": pattern,
        "file_glob": file_glob,
    })


@tool
def execute_python(code: str, timeout: int = 30) -> str:
    """执行Python代码并返回结果。代码在受限沙箱中运行，有超时限制和危险操作拦截。"""
    return tool_execute_python({"code": code, "timeout": timeout})


# execute_sql 由外部 skill 提供


@tool
def execute_java(code: str, class_name: str = "Main", timeout: int = 60) -> str:
    """编译并运行Java代码。将代码写入临时文件，用javac编译后java运行。"""
    return tool_execute_java({
        "code": code,
        "class_name": class_name,
        "timeout": timeout,
    })


@tool
def analyze_python(project_path: str, focus: str = "all") -> str:
    """深入分析Python项目。识别入口点、import依赖、类/函数定义、配置文件、测试覆盖等。"""
    return tool_analyze_python({"project_path": project_path, "focus": focus})


@tool
def analyze_java(project_path: str, focus: str = "all") -> str:
    """深入分析Java项目。识别Maven/Gradle结构、Spring Boot组件、类继承关系、设计模式等。"""
    return tool_analyze_java({"project_path": project_path, "focus": focus})


@tool
def analyze_sql(sql: str, focus: str = "all") -> str:
    """分析SQL脚本。检查语法问题、识别表依赖关系、提取字段映射、分析分区策略等。"""
    return tool_analyze_sql({"sql": sql, "focus": focus})


@tool
def code_review(code: str, language: str, context: str = "") -> str:
    """代码审查工具。从简洁性、正确性、规范性三个维度审查代码，附带置信度评分过滤误报。"""
    return tool_code_review({
        "code": code,
        "language": language,
        "context": context,
    })


# ---- Git 工作流工具 ----

@tool
def git_status(repo_path: str = ".") -> str:
    """查看Git仓库状态。返回当前分支、暂存区和工作区的变更摘要。"""
    return tool_git_status({"repo_path": repo_path})


@tool
def git_diff(repo_path: str = ".", target: str = "unstaged", file_path: str = "", max_lines: int = 200) -> str:
    """查看Git差异。支持暂存区(staged)、工作区(unstaged)、与上次提交(HEAD)的差异。"""
    args = {"repo_path": repo_path, "target": target, "max_lines": max_lines}
    if file_path:
        args["file_path"] = file_path
    return tool_git_diff(args)


@tool
def git_commit(message: str, repo_path: str = ".", add_all: bool = False) -> str:
    """提交Git变更。将暂存区的修改提交到仓库。设置add_all=True可暂存所有变更后提交。"""
    return tool_git_commit({"message": message, "repo_path": repo_path, "add_all": add_all})


@tool
def git_checkout(action: str, repo_path: str = ".", branch: str = "", file_path: str = "") -> str:
    """切换Git分支或恢复文件。action支持: switch(切换分支), create(创建新分支), restore(恢复文件)。"""
    args = {"action": action, "repo_path": repo_path}
    if branch:
        args["branch"] = branch
    if file_path:
        args["file_path"] = file_path
    return tool_git_checkout(args)


# ---- 语义搜索工具 ----

@tool
def semantic_search(project_path: str, query: str, top_k: int = 10, force_reindex: bool = False) -> str:
    """语义代码搜索。基于AI嵌入理解代码含义，用自然语言描述即可找到相关代码。比search_code更智能。"""
    return tool_semantic_search({
        "project_path": project_path,
        "query": query,
        "top_k": top_k,
        "force_reindex": force_reindex,
    })


# 核心工具列表（不含 skill 提供的工具，skill 工具在运行时动态合并）
CORE_TOOLS = [
    scan_project, read_file, write_file, edit_file, search_code,
    execute_python, execute_java,
    analyze_python, analyze_java, analyze_sql,
    code_review,
    git_status, git_diff, git_commit, git_checkout,
    semantic_search,
]

# Tool 名称到函数的映射
CORE_TOOL_MAP = {t.name: t for t in CORE_TOOLS}


def get_all_tools():
    """获取所有工具（核心 + 外部 skill 动态加载）"""
    from skill_loader import get_all_tools as get_skill_tools
    return CORE_TOOLS + get_skill_tools()


def get_all_tool_map():
    """获取所有工具映射（核心 + 外部 skill 动态加载）"""
    tool_map = dict(CORE_TOOL_MAP)
    from skill_loader import get_all_tools as get_skill_tools
    for t in get_skill_tools():
        tool_map[t.name] = t
    return tool_map


# 向后兼容
LANGCHAIN_TOOLS = CORE_TOOLS
LANGCHAIN_TOOL_MAP = CORE_TOOL_MAP


def handle_tool_calls_parallel(tool_calls: list[dict]) -> list[dict]:
    """
    并行执行工具调用

    Args:
        tool_calls: LLM 返回的 tool_calls 列表，每个元素包含 function.name 和 function.arguments

    Returns:
        工具执行结果列表，格式兼容 LangChain message
    """
    # 使用完整的工具映射（核心 + skill），而非仅核心
    tool_map = get_all_tool_map()
    results = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_to_id = {}
        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
            tool_fn = tool_map.get(fn_name)

            if tool_fn:
                future = pool.submit(tool_fn.invoke, fn_args)
                future_to_id[future] = tc["id"]
            else:
                results[tc["id"]] = f"未知工具: {fn_name}"

        for future in as_completed(future_to_id):
            tc_id = future_to_id[future]
            try:
                results[tc_id] = str(future.result())
            except Exception as e:
                results[tc_id] = f"工具执行异常: {str(e)}"

    # 按 tool_calls 顺序返回结果
    return [
        {"tool_call_id": tc_id, "role": "tool", "content": results.get(tc_id, "无结果")}
        for tc_id in [tc["id"] for tc in tool_calls]
    ]
