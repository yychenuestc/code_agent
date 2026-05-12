# -*- coding: utf-8 -*-
"""
代码执行工具: execute_python, execute_java
"""
import os
import sys
import subprocess
import tempfile

from core.config import PYTHON_TIMEOUT, JAVA_TIMEOUT, MAX_OUTPUT_LENGTH
from core.hooks import check_python_safety, check_java_safety


# ============ 工具Schema定义 ============

SCHEMAS = [
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
    # execute_sql 由外部 skill 提供
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
]


# ============ 工具执行函数 ============

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
# 安全检查和 SQL 调用由 skill 内部提供


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


TOOL_DISPATCH = {
    "execute_python": tool_execute_python,
    "execute_java": tool_execute_java,
}
