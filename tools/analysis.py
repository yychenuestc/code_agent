# -*- coding: utf-8 -*-
"""
项目分析与代码审查工具: analyze_python, analyze_java, analyze_sql, code_review
"""
import os
import re
import ast

from core.config import MAX_OUTPUT_LENGTH
from core.hooks import filter_review_issues


# ============ 工具Schema定义 ============

SCHEMAS = [
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
        if not sql.strip().endswith(';') and sql.strip().upper().startswith('SELECT'):
            issues.append("警告: SELECT语句未以分号结尾")
        if 'SELECT *' in sql.upper():
            issues.append("建议: 避免SELECT *，明确列出字段")
        if sql.upper().count('JOIN') > 5:
            issues.append("注意: 多表JOIN(>5)，关注性能和可读性")
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
        source_tables = re.findall(r'(?:FROM|JOIN)\s+(\w+\.\w+|\w+)', sql, re.IGNORECASE)
        target_tables = re.findall(r'(?:INSERT\s+OVERWRITE\s+TABLE|INSERT\s+INTO)\s+(\w+\.\w+|\w+)', sql, re.IGNORECASE)
        cte_names = re.findall(r'(\w+)\s+AS\s*\(', sql, re.IGNORECASE)

        if source_tables:
            result_lines.append(f"\n源表: {', '.join(set(source_tables))}")
        if target_tables:
            result_lines.append(f"目标表: {', '.join(set(target_tables))}")
        if cte_names:
            result_lines.append(f"CTE: {', '.join(cte_names)}")

    # 字段映射分析
    if focus in ("fields", "all"):
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if select_match:
            fields_str = select_match.group(1)
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


TOOL_DISPATCH = {
    "analyze_python": tool_analyze_python,
    "analyze_java": tool_analyze_java,
    "analyze_sql": tool_analyze_sql,
    "code_review": tool_code_review,
}
