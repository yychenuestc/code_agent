# -*- coding: utf-8 -*-
"""
工具定义与执行函数 - 核心工具（10个）
SQL 查询工具由外部 skill 提供，不在此文件中
"""
import os
import re
import ast
import sys
import json
import subprocess
import tempfile
from config import PYTHON_TIMEOUT, JAVA_TIMEOUT, MAX_OUTPUT_LENGTH
from hooks import (
    check_python_safety, check_java_safety,
    check_file_write_safety, filter_review_issues
)

# ============ 工具定义（OpenAI function calling格式） ============

TOOLS = [
    # ---- 文件与项目操作 ----
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
    # ---- 代码执行 ----
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": "执行Python代码并返回结果。代码在受限沙箱中运行，有超时限制和危险操作拦截。用于数据计算、脚本验证、快速原型等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的Python代码"},
                    "timeout": {"type": "integer", "description": "超时秒数（可选，默认30）"}
                },
                "required": ["code"]
            }
        }
    },
    # execute_sql 已移至外部 skill
    {
        "type": "function",
        "function": {
            "name": "execute_java",
            "description": "编译并运行Java代码。将代码写入临时文件，用javac编译后java运行。用于验证Java代码片段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Java源码（需包含完整类定义）"},
                    "class_name": {"type": "string", "description": "主类名（默认Main）"},
                    "timeout": {"type": "integer", "description": "超时秒数（可选，默认60）"}
                },
                "required": ["code"]
            }
        }
    },
    # ---- 项目分析 ----
    {
        "type": "function",
        "function": {
            "name": "analyze_python",
            "description": "深入分析Python项目。识别入口点、import依赖、类/函数定义、配置文件、测试覆盖等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "项目根目录路径"},
                    "focus": {"type": "string", "description": "分析重点: structure/dependencies/entry_points/all", "enum": ["structure", "dependencies", "entry_points", "all"]}
                },
                "required": ["project_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_java",
            "description": "深入分析Java项目。识别Maven/Gradle结构、Spring Boot组件、类继承关系、设计模式等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string", "description": "项目根目录路径"},
                    "focus": {"type": "string", "description": "分析重点: structure/spring/patterns/all", "enum": ["structure", "spring", "patterns", "all"]}
                },
                "required": ["project_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_sql",
            "description": "分析SQL脚本。检查语法问题、识别表依赖关系、提取字段映射、分析分区策略等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "要分析的SQL脚本"},
                    "focus": {"type": "string", "description": "分析重点: syntax/lineage/fields/all", "enum": ["syntax", "lineage", "fields", "all"]}
                },
                "required": ["sql"]
            }
        }
    },
    # ---- 质量保障 ----
    {
        "type": "function",
        "function": {
            "name": "code_review",
            "description": "代码审查工具。从简洁性、正确性、规范性三个维度审查代码，附带置信度评分过滤误报。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要审查的代码"},
                    "language": {"type": "string", "description": "编程语言: python/java/sql"},
                    "context": {"type": "string", "description": "代码上下文说明（可选）"}
                },
                "required": ["code", "language"]
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
    indicators = {
        "python": ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile", "manage.py", "app.py"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "sql": [".sql"],
    }

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
        # 跳过隐藏目录和常见忽略目录
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
        for f in files[:20]:  # 每目录最多20个文件
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
    end_line = args.get("end_line")

    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        total_lines = len(lines)
        start = max(1, start_line) - 1
        end = end_line or total_lines
        selected = lines[start:end]

        result_lines = [f"文件: {file_path} (共{total_lines}行, 显示第{start+1}-{min(end, total_lines)}行)\n"]
        for i, line in enumerate(selected, start=start + 1):
            result_lines.append(f"{i:4d} | {line.rstrip()}")

        result = "\n".join(result_lines)
        if len(result) > MAX_OUTPUT_LENGTH:
            result = result[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
        return result
    except Exception as e:
        return f"读取失败: {e}"


def tool_write_file(args):
    file_path = args["file_path"]
    content = args["content"]

    # Hook安全检查
    hook_result = check_file_write_safety(file_path, content)
    if not hook_result.allowed:
        return hook_result.message
    if hook_result.needs_confirm:
        # 返回确认提示，由LLM决定是否继续
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
                    # 简单glob匹配
                    if file_glob.startswith('*.'):
                        ext = file_glob[1:]  # .py, .java
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
                except (PermissionError, UnicodeDecodeError):
                    continue
    except Exception as e:
        return f"搜索失败: {e}"

    if not matches:
        return f"未找到匹配 '{pattern}' 的内容"

    return "\n".join(matches)


def tool_execute_python(args):
    code = args["code"]
    timeout = args.get("timeout", PYTHON_TIMEOUT)

    # Hook安全检查
    hook_result = check_python_safety(code)
    if not hook_result.allowed:
        return hook_result.message
    if hook_result.needs_confirm:
        return f"[需确认] {hook_result.confirm_message} 如确认执行，请直接说明。"

    try:
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True, text=True, timeout=timeout,
            encoding='utf-8', errors='replace'
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"

        if result.returncode != 0:
            output = f"退出码: {result.returncode}\n{output}"

        if len(output) > MAX_OUTPUT_LENGTH:
            output = output[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
        return output or "执行完成（无输出）"

    except subprocess.TimeoutExpired:
        return f"执行超时（{timeout}秒）"
    except Exception as e:
        return f"执行失败: {e}"


# tool_execute_sql 已移至外部 skill
# 安全检查和 Bigda 调用由 skill 内部的 check_sql_safety + execute_sql 提供


def tool_execute_java(args):
    code = args["code"]
    class_name = args.get("class_name", "Main")
    timeout = args.get("timeout", JAVA_TIMEOUT)

    # Hook安全检查
    hook_result = check_java_safety(code)
    if not hook_result.allowed:
        return hook_result.message

    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        java_file = os.path.join(tmpdir, f"{class_name}.java")
        try:
            with open(java_file, 'w', encoding='utf-8') as f:
                f.write(code)
        except Exception as e:
            return f"写入Java文件失败: {e}"

        # 编译
        try:
            compile_result = subprocess.run(
                ['javac', java_file],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace', cwd=tmpdir
            )
            if compile_result.returncode != 0:
                return f"编译失败:\n{compile_result.stderr}"
        except FileNotFoundError:
            return "javac 未找到，请确认JDK已安装并配置PATH"
        except subprocess.TimeoutExpired:
            return "编译超时"

        # 运行
        try:
            run_result = subprocess.run(
                ['java', '-cp', '.', class_name],
                capture_output=True, text=True, timeout=timeout,
                encoding='utf-8', errors='replace', cwd=tmpdir
            )
            output = ""
            if run_result.stdout:
                output += run_result.stdout
            if run_result.stderr:
                output += f"\n[stderr]\n{run_result.stderr}"

            if run_result.returncode != 0:
                output = f"退出码: {run_result.returncode}\n{output}"

            if len(output) > MAX_OUTPUT_LENGTH:
                output = output[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
            return output or "执行完成（无输出）"

        except subprocess.TimeoutExpired:
            return f"运行超时（{timeout}秒）"
        except Exception as e:
            return f"运行失败: {e}"


def tool_analyze_python(args):
    project_path = args["project_path"]
    focus = args.get("focus", "all")

    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    result_lines = [f"Python项目分析: {project_path}\n"]

    # 收集所有Python文件
    py_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('__pycache__', 'venv', '.venv', 'node_modules', '.git')]
        for f in files:
            if f.endswith('.py'):
                py_files.append(os.path.join(root, f))

    result_lines.append(f"Python文件数: {len(py_files)}")

    # 分析入口点
    if focus in ("entry_points", "all"):
        entry_points = []
        for fp in py_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                if 'if __name__' in content:
                    rel = os.path.relpath(fp, project_path)
                    entry_points.append(rel)
                # FastAPI/Flask路由
                if any(kw in content for kw in ['@app.route', '@router.', 'app = FastAPI', 'app = Flask']):
                    rel = os.path.relpath(fp, project_path)
                    entry_points.append(f"{rel} (Web入口)")
            except:
                continue
        result_lines.append(f"\n入口点:")
        for ep in entry_points[:10]:
            result_lines.append(f"  - {ep}")

    # 分析依赖
    if focus in ("dependencies", "all"):
        imports = {}
        for fp in py_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            pkg = alias.name.split('.')[0]
                            imports[pkg] = imports.get(pkg, 0) + 1
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            pkg = node.module.split('.')[0]
                            imports[pkg] = imports.get(pkg, 0) + 1
            except:
                continue

        result_lines.append(f"\n依赖统计 (Top 15):")
        for pkg, count in sorted(imports.items(), key=lambda x: x[1], reverse=True)[:15]:
            result_lines.append(f"  {pkg:20s} {count}次引用")

    # 分析类和函数
    if focus in ("structure", "all"):
        classes = []
        functions = []
        for fp in py_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                tree = ast.parse(content)
                rel = os.path.relpath(fp, project_path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        classes.append(f"{rel}:{node.lineno} class {node.name}")
                    elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
                        functions.append(f"{rel}:{node.lineno} def {node.name}()")
            except:
                continue

        result_lines.append(f"\n类定义 ({len(classes)}个):")
        for c in classes[:20]:
            result_lines.append(f"  {c}")
        result_lines.append(f"\n顶层函数 ({len(functions)}个):")
        for f in functions[:20]:
            result_lines.append(f"  {f}")

    output = "\n".join(result_lines)
    if len(output) > MAX_OUTPUT_LENGTH:
        output = output[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
    return output


def tool_analyze_java(args):
    project_path = args["project_path"]
    focus = args.get("focus", "all")

    if not os.path.exists(project_path):
        return f"路径不存在: {project_path}"

    result_lines = [f"Java项目分析: {project_path}\n"]

    # 检测构建工具
    is_maven = os.path.exists(os.path.join(project_path, "pom.xml"))
    is_gradle = os.path.exists(os.path.join(project_path, "build.gradle")) or \
                os.path.exists(os.path.join(project_path, "build.gradle.kts"))
    build_tool = "Maven" if is_maven else "Gradle" if is_gradle else "未知"
    result_lines.append(f"构建工具: {build_tool}")

    # 收集Java文件
    java_files = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('target', 'build', '.gradle', '.idea', 'node_modules')]
        for f in files:
            if f.endswith('.java'):
                java_files.append(os.path.join(root, f))

    result_lines.append(f"Java文件数: {len(java_files)}")

    # Spring Boot分析
    if focus in ("spring", "all"):
        spring_components = {
            "@RestController": [], "@Controller": [], "@Service": [],
            "@Repository": [], "@Component": [], "@Configuration": [],
            "@SpringBootApplication": [],
        }
        for fp in java_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                rel = os.path.relpath(fp, project_path)
                for anno in spring_components:
                    if anno in content:
                        spring_components[anno].append(rel)
            except:
                continue

        has_spring = any(v for v in spring_components.values())
        if has_spring:
            result_lines.append(f"\nSpring Boot组件:")
            for anno, files in spring_components.items():
                if files:
                    result_lines.append(f"  {anno} ({len(files)}个):")
                    for f in files[:5]:
                        result_lines.append(f"    - {f}")
                    if len(files) > 5:
                        result_lines.append(f"    ... +{len(files) - 5} more")

    # 设计模式识别
    if focus in ("patterns", "all"):
        patterns = {
            "工厂模式": [],
            "策略模式": [],
            "单例模式": [],
            "建造者模式": [],
            "观察者模式": [],
        }
        for fp in java_files:
            fname = os.path.basename(fp).replace('.java', '')
            rel = os.path.relpath(fp, project_path)
            if fname.endswith("Factory"):
                patterns["工厂模式"].append(rel)
            elif fname.endswith("Strategy"):
                patterns["策略模式"].append(rel)
            elif "Singleton" in fname or "getInstance" in open(fp, 'r', errors='replace').read():
                patterns["单例模式"].append(rel)
            elif fname.endswith("Builder"):
                patterns["建造者模式"].append(rel)
            elif fname.endswith("Listener") or fname.endswith("Observer"):
                patterns["观察者模式"].append(rel)

        found = {k: v for k, v in patterns.items() if v}
        if found:
            result_lines.append(f"\n设计模式:")
            for p, files in found.items():
                result_lines.append(f"  {p}: {', '.join(files[:5])}")

    # 类分析
    if focus in ("structure", "all"):
        classes = []
        for fp in java_files:
            try:
                with open(fp, 'r', encoding='utf-8', errors='replace') as f:
                    for line_no, line in enumerate(f, 1):
                        # 简单匹配类定义
                        match = re.match(r'.*public\s+(class|interface|enum|abstract\s+class)\s+(\w+)', line)
                        if match:
                            rel = os.path.relpath(fp, project_path)
                            classes.append(f"{rel}:{line_no} {match.group(1)} {match.group(2)}")
            except:
                continue

        result_lines.append(f"\n类/接口定义 ({len(classes)}个):")
        for c in classes[:20]:
            result_lines.append(f"  {c}")

    output = "\n".join(result_lines)
    if len(output) > MAX_OUTPUT_LENGTH:
        output = output[:MAX_OUTPUT_LENGTH] + "\n... (输出过长，已截断)"
    return output


def tool_analyze_sql(args):
    sql = args["sql"]
    focus = args.get("focus", "all")

    result_lines = ["SQL脚本分析:\n"]

    # 语法检查
    if focus in ("syntax", "all"):
        issues = []
        # 简单语法检查
        if not sql.strip().endswith(';') and sql.strip().upper().startswith('SELECT'):
            issues.append("警告: SELECT语句未以分号结尾")
        if 'SELECT *' in sql.upper():
            issues.append("建议: 避免SELECT *，明确列出字段")
        if sql.upper().count('JOIN') > 5:
            issues.append("注意: 多表JOIN(>5)，关注性能和可读性")
        # 检查分区过滤
        if 'PARTITIONED' not in sql.upper() and 'dt =' not in sql.lower() and 'dt =' not in sql:
            if 'FROM' in sql.upper():
                issues.append("建议: 查询未包含分区过滤(dt)，可能导致全表扫描")

        if issues:
            result_lines.append("语法检查:")
            for issue in issues:
                result_lines.append(f"  - {issue}")
        else:
            result_lines.append("语法检查: 未发现明显问题")

    # 表血缘分析
    if focus in ("lineage", "all"):
        # 提取源表
        source_tables = re.findall(r'(?:FROM|JOIN)\s+(\w+\.\w+|\w+)', sql, re.IGNORECASE)
        # 提取目标表
        target_tables = re.findall(r'(?:INSERT\s+OVERWRITE\s+TABLE|INSERT\s+INTO)\s+(\w+\.\w+|\w+)', sql, re.IGNORECASE)
        # 提取CTE
        cte_names = re.findall(r'(\w+)\s+AS\s*\(', sql, re.IGNORECASE)

        if source_tables:
            result_lines.append(f"\n源表: {', '.join(set(source_tables))}")
        if target_tables:
            result_lines.append(f"目标表: {', '.join(set(target_tables))}")
        if cte_names:
            result_lines.append(f"CTE: {', '.join(cte_names)}")

    # 字段映射分析
    if focus in ("fields", "all"):
        # 提取SELECT字段
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            fields_str = select_match.group(1)
            # 简单分割字段
            fields = [f.strip() for f in fields_str.split(',') if f.strip()]
            result_lines.append(f"\nSELECT字段 ({len(fields)}个):")
            for i, f in enumerate(fields[:30], 1):
                result_lines.append(f"  {i}. {f[:80]}")
            if len(fields) > 30:
                result_lines.append(f"  ... +{len(fields) - 30} more fields")

    return "\n".join(result_lines)


def tool_code_review(args):
    code = args["code"]
    language = args["language"]
    context = args.get("context", "")

    # 基于规则的静态检查（快速扫描，作为LLM审查的补充）
    issues = []

    # 通用检查
    if len(code) > 500 and not any(c in code for c in ['# TODO', '// TODO', '/*']):
        if code.count('\n') > 50:
            issues.append({
                "dimension": "简洁性",
                "severity": "MINOR",
                "confidence": 70,
                "message": "代码较长，考虑拆分函数/方法"
            })

    # Python专项检查
    if language == "python":
        if 'except:' in code and 'except Exception' not in code:
            issues.append({
                "dimension": "正确性",
                "severity": "IMPORTANT",
                "confidence": 90,
                "message": "避免裸except，应指定异常类型"
            })
        if 'print(' in code and 'def ' in code:
            issues.append({
                "dimension": "规范性",
                "severity": "MINOR",
                "confidence": 75,
                "message": "生产代码应使用logging而非print"
            })

    # Java专项检查
    elif language == "java":
        if 'System.out.println' in code:
            issues.append({
                "dimension": "规范性",
                "severity": "IMPORTANT",
                "confidence": 90,
                "message": "使用SLF4J日志框架替代System.out.println"
            })
        if 'e.printStackTrace()' in code:
            issues.append({
                "dimension": "正确性",
                "severity": "IMPORTANT",
                "confidence": 95,
                "message": "e.printStackTrace()不应出现在生产代码中，使用logger.error()"
            })

    # SQL专项检查
    elif language == "sql":
        if 'SELECT *' in code.upper():
            issues.append({
                "dimension": "规范性",
                "severity": "MINOR",
                "confidence": 85,
                "message": "避免SELECT *，明确列出字段"
            })
        if 'LIKE' in code.upper() and '%' in code:
            if code.upper().count('LIKE') > 3:
                issues.append({
                    "dimension": "正确性",
                    "severity": "IMPORTANT",
                    "confidence": 80,
                    "message": "多个LIKE模糊查询可能影响性能"
                })

    # 置信度过滤
    filtered = filter_review_issues(issues)

    if not filtered:
        return "规则扫描通过，未发现高置信度问题。建议LLM深度审查。"

    result_lines = ["代码审查结果（规则扫描）:\n"]
    for issue in filtered:
        result_lines.append(
            f"  [{issue['dimension']}] {issue['severity']} (置信度{issue['confidence']}%)"
            f"\n    {issue['message']}"
        )

    return "\n".join(result_lines)


# ============ 工具调度表 ============

TOOL_DISPATCH = {
    "scan_project": tool_scan_project,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "search_code": tool_search_code,
    "execute_python": tool_execute_python,
    # execute_sql 由外部 skill 提供
    "execute_java": tool_execute_java,
    "analyze_python": tool_analyze_python,
    "analyze_java": tool_analyze_java,
    "analyze_sql": tool_analyze_sql,
    "code_review": tool_code_review,
}
