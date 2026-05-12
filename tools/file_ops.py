# -*- coding: utf-8 -*-
"""
文件与项目操作工具: scan_project, read_file, write_file, edit_file
"""
import os
import ast

from core.config import MAX_OUTPUT_LENGTH
from core.hooks import check_file_write_safety


# ============ 工具Schema定义 ============

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "scan_project",
            "description": "扫描项目目录结构，识别编程语言、框架、构建工具。输入项目根目录路径，返回项目概览信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "项目根目录路径"},
                    "depth": {"type": "integer", "description": "扫描深度（默认3，最大5）"}
                },
                "required": ["project_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的内容。支持查看源码、配置文件等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件完整路径"},
                    "start_line": {"type": "integer", "description": "起始行号（从1开始，可选）"},
                    "end_line": {"type": "integer", "description": "结束行号（可选）"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入或创建文件。对破坏性操作会进行安全检查。用于创建新文件或覆盖已有文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件完整路径"},
                    "content": {"type": "string", "description": "要写入的内容"}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "精确编辑已有文件，支持三种模式: 1) line_range: 替换指定行范围的内容; 2) replace: 将旧文本替换为新文本; 3) function_replace: 替换指定函数/方法的完整定义。比 write_file 更安全，只修改目标区域。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件完整路径"},
                    "mode": {"type": "string", "description": "编辑模式: line_range/replace/function_replace", "enum": ["line_range", "replace", "function_replace"]},
                    "start_line": {"type": "integer", "description": "起始行号(line_range模式，从1开始)"},
                    "end_line": {"type": "integer", "description": "结束行号(line_range模式，包含此行)"},
                    "old_text": {"type": "string", "description": "要替换的旧文本(replace模式)"},
                    "new_text": {"type": "string", "description": "替换后的新文本(replace模式)"},
                    "function_name": {"type": "string", "description": "要替换的函数/方法名(function_replace模式)"},
                    "new_code": {"type": "string", "description": "新的函数/方法完整代码(function_replace模式)"},
                    "class_name": {"type": "string", "description": "类名(function_replace模式，替换类方法时需要)"}
                },
                "required": ["file_path", "mode"]
            }
        }
    },
]


# ============ 工具执行函数 ============

def tool_scan_project(args):
    project_path = args["project_path"]
    depth = min(args.get("depth", 3), 5)

    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    # 识别项目类型
    detected_langs = set()
    build_tools = []
    frameworks = []

    try:
        top_files = os.listdir(project_path)
    except PermissionError:
        return f"无权限访问: {project_path}"

    for f in top_files:
        fl = f.lower()
        if fl in ("setup.py", "pyproject.toml", "requirements.txt", "pipfile"):
            detected_langs.add("python")
            build_tools.append(f)
        if fl in ("pom.xml",):
            detected_langs.add("java")
            build_tools.append("Maven")
        if fl in ("build.gradle", "build.gradle.kts"):
            detected_langs.add("java")
            build_tools.append("Gradle")
        if fl == "manage.py":
            frameworks.append("Django")
        if fl == "app.py" or fl == "main.py":
            frameworks.append("Flask/FastAPI")

    # 检查src目录结构
    src_indicators = {"java": False, "python": False}
    for root, dirs, files in os.walk(project_path):
        rel = os.path.relpath(root, project_path)
        level = rel.count(os.sep)
        if level > depth:
            dirs.clear()
            continue
        if "src/main/java" in rel.replace("\\", "/"):
            src_indicators["java"] = True
        if any(f.endswith(".py") for f in files):
            src_indicators["python"] = True

    if src_indicators["java"]:
        detected_langs.add("java")
    if src_indicators["python"]:
        detected_langs.add("python")

    # 构建目录树
    lines = [f"项目概览: {project_path}"]
    lines.append(f"检测语言: {', '.join(detected_langs) or '未知'}")
    if build_tools:
        lines.append(f"构建工具: {', '.join(build_tools)}")
    if frameworks:
        lines.append(f"框架: {', '.join(frameworks)}")
    lines.append("")

    # 目录树
    lines.append(f"目录结构 (深度{depth}层):")
    dir_count = 0
    file_count = 0
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', '.git', '.idea', 'target', 'build', '.gradle', 'venv', '.venv')]
        rel = os.path.relpath(root, project_path)
        level = rel.count(os.sep)
        if level >= depth:
            dirs.clear()
            continue
        indent = "  " * level
        dirname = os.path.basename(root) if rel != "." else "."
        lines.append(f"{indent}{dirname}/")
        dir_count += 1
        for f in files[:20]:
            lines.append(f"{indent}  {f}")
            file_count += 1
        if len(files) > 20:
            lines.append(f"{indent}  ... +{len(files) - 20} more files")

    lines.append(f"\n统计: {dir_count}个目录, {file_count}个文件")
    result = "\n".join(lines)
    if len(result) > MAX_OUTPUT_LENGTH:
        result = result[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
    return result


def tool_read_file(args):
    file_path = args["file_path"]
    start_line = args.get("start_line", 1)
    end_line = args.get("end_line", 0)

    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
    except Exception as e:
        return f"读取失败: {e}"

    total = len(all_lines)
    if end_line == 0 or end_line > total:
        end_line = total

    selected = all_lines[start_line - 1:end_line]
    # 添加行号
    numbered = []
    for i, line in enumerate(selected, start_line):
        numbered.append(f"{i}: {line.rstrip()}")

    result = "\n".join(numbered)
    if len(result) > MAX_OUTPUT_LENGTH:
        result = result[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"

    header = f"文件: {file_path} (共{total}行, 显示{start_line}-{end_line})"
    return f"{header}\n{result}"


def tool_write_file(args):
    file_path = args["file_path"]
    content = args["content"]

    # Hook安全检查
    hook_result = check_file_write_safety(file_path, content)
    if not hook_result.allowed:
        return hook_result.message
    if hook_result.needs_confirm:
        return f"[需确认] {hook_result.confirm_message} 如确认写入，请直接说明。"

    try:
        os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        size = len(content.encode('utf-8'))
        lines = content.count('\n') + 1
        return f"已写入: {file_path} ({lines}行, {size}字节)"
    except Exception as e:
        return f"写入失败: {e}"


def _find_function_range(lines, func_name, class_name=None):
    """使用AST精确定位函数/方法的行范围"""
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if class_name:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == func_name:
                        return item.lineno, item.end_lineno
        else:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                return node.lineno, node.end_lineno
    return None


def tool_edit_file(args):
    """精确编辑文件，支持行范围替换、文本替换、函数替换三种模式"""
    file_path = args["file_path"]
    mode = args["mode"]

    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.split('\n')
        original_count = len(lines)
    except Exception as e:
        return f"读取文件失败: {e}"

    changed = False

    if mode == "line_range":
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        new_text = args.get("new_text", "")

        if start_line is None or end_line is None:
            return "line_range模式需要 start_line 和 end_line 参数"

        if start_line < 1 or end_line > original_count or start_line > end_line:
            return f"行范围无效: start_line={start_line}, end_line={end_line}, 文件共{original_count}行"

        replaced = "\n".join(lines[start_line - 1:end_line])
        new_lines = new_text.split('\n') if new_text else []
        lines[start_line - 1:end_line] = new_lines
        changed = True

        result_msg = f"已编辑: {file_path}\n"
        result_msg += f"  替换行: {start_line}-{end_line} ({end_line - start_line + 1}行) → {len(new_lines)}行\n"
        result_msg += f"  原内容预览: {replaced[:200]}..."

    elif mode == "replace":
        old_text = args.get("old_text", "")
        new_text = args.get("new_text", "")

        if not old_text:
            return "replace模式需要 old_text 参数"

        count = content.count(old_text)
        if count == 0:
            return f"未找到要替换的文本。请先用 read_file 确认文件内容。"
        if count > 1:
            positions = []
            idx = 0
            for i in range(min(count, 5)):
                pos = content.find(old_text, idx)
                line_no = content[:pos].count('\n') + 1
                positions.append(f"第{line_no}行")
                idx = pos + 1
            return f"找到{count}处匹配，无法确定替换哪一处。匹配位置: {', '.join(positions)}。请提供更多上下文使匹配唯一。"

        content = content.replace(old_text, new_text, 1)
        lines = content.split('\n')
        changed = True
        result_msg = f"已编辑: {file_path}\n"
        result_msg += f"  替换1处文本 ({len(old_text)}字符 → {len(new_text)}字符)"

    elif mode == "function_replace":
        func_name = args.get("function_name", "")
        class_name = args.get("class_name")
        new_code = args.get("new_code", "")

        if not func_name:
            return "function_replace模式需要 function_name 参数"

        range_result = _find_function_range(lines, func_name, class_name)
        if range_result is None:
            scope = f"{class_name}.{func_name}" if class_name else func_name
            return f"未找到函数: {scope}。请先用 read_file 确认函数名。"

        start_line, end_line = range_result
        replaced = "\n".join(lines[start_line - 1:end_line])
        new_lines = new_code.split('\n') if new_code else []
        lines[start_line - 1:end_line] = new_lines
        changed = True

        scope = f"{class_name}.{func_name}" if class_name else func_name
        result_msg = f"已编辑: {file_path}\n"
        result_msg += f"  替换函数: {scope} (行{start_line}-{end_line}, {end_line - start_line + 1}行 → {len(new_lines)}行)"

    else:
        return f"未知编辑模式: {mode}，支持: line_range, replace, function_replace"

    if changed:
        new_content = "\n".join(lines)
        hook_result = check_file_write_safety(file_path, new_content)
        if not hook_result.allowed:
            return hook_result.message
        if hook_result.needs_confirm:
            return f"[需确认] {hook_result.confirm_message} 如确认写入，请直接说明。"

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            new_count = len(lines)
            result_msg += f"\n  文件总行数: {original_count} → {new_count}"
        except Exception as e:
            return f"写入文件失败: {e}"

    return result_msg


TOOL_DISPATCH = {
    "scan_project": tool_scan_project,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
}
