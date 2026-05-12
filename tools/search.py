# -*- coding: utf-8 -*-
"""
代码搜索工具: search_code, semantic_search
"""
import os
import re

from core.config import MAX_OUTPUT_LENGTH


# ============ 工具Schema定义 ============

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在项目中搜索代码内容。支持正则表达式。用于查找函数定义、类引用、配置项等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "搜索的根目录"},
                    "pattern": {"type": "string", "description": "搜索模式（支持正则）"},
                    "file_glob": {"type": "string", "description": "文件过滤（如 '*.py', '*.java'），可选"}
                },
                "required": ["project_path", "pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "语义代码搜索。基于AI嵌入向量理解代码含义，用自然语言描述即可找到相关代码。比search_code更智能，不依赖精确关键词匹配。首次使用需构建索引。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "项目根目录路径"},
                    "query": {"type": "string", "description": "自然语言搜索描述（如'处理用户认证的逻辑'、'数据库连接配置'）"},
                    "top_k": {"type": "integer", "description": "返回结果数量（默认10，最大20）"},
                    "force_reindex": {"type": "boolean", "description": "是否强制重建索引（默认false，仅在代码大幅变更后使用）"}
                },
                "required": ["project_path", "query"]
            }
        }
    },
]


# ============ 工具执行函数 ============

def tool_search_code(args):
    project_path = args["project_path"]
    pattern = args["pattern"]
    file_glob = args.get("file_glob", "")

    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"正则表达式错误: {e}"

    matches = []
    try:
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                       ('node_modules', '__pycache__', '.git', '.idea', 'target', 'build', '.gradle')]
            for fname in files:
                if file_glob:
                    if file_glob.startswith('*.'):
                        ext = file_glob[1:]
                        if not fname.endswith(ext):
                            continue
                    elif file_glob not in fname:
                        continue

                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        for line_no, line in enumerate(f, 1):
                            if regex.search(line):
                                rel_path = os.path.relpath(fpath, project_path)
                                matches.append(f"{rel_path}:{line_no}: {line.rstrip()}")
                                if len(matches) >= 50:
                                    return "\n".join(matches) + "\n... (结果过多，已截断50条)"
                except (IOError, UnicodeDecodeError):
                    continue

    except Exception as e:
        return f"搜索失败: {e}"

    if not matches:
        return "未找到匹配结果"

    return "\n".join(matches)


def tool_semantic_search(args):
    """语义代码搜索（RAG）"""
    from tools.semantic_search import semantic_search

    project_path = args["project_path"]
    query = args["query"]
    top_k = min(args.get("top_k", 10), 20)
    force_reindex = args.get("force_reindex", False)

    return semantic_search(project_path, query, top_k=top_k, force_reindex=force_reindex)


TOOL_DISPATCH = {
    "search_code": tool_search_code,
    "semantic_search": tool_semantic_search,
}
