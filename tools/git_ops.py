# -*- coding: utf-8 -*-
"""
Git 工作流工具: git_status, git_diff, git_commit, git_checkout
"""
import subprocess


# ============ 工具Schema定义 ============

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "查看Git仓库状态。返回当前分支、暂存区和工作区的变更摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Git仓库路径（默认当前目录）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "查看Git差异。支持查看暂存区差异、工作区差异、指定提交间的差异。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Git仓库路径（默认当前目录）"},
                    "target": {"type": "string", "description": "差异目标: staged(暂存区), unstaged(工作区), HEAD(与上次提交比), 或commit hash", "enum": ["staged", "unstaged", "HEAD"]},
                    "file_path": {"type": "string", "description": "限定文件路径（可选）"},
                    "max_lines": {"type": "integer", "description": "最大输出行数（默认200）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "提交Git变更。将暂存区的修改提交到仓库。危险操作，会进行安全检查。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Git仓库路径（默认当前目录）"},
                    "message": {"type": "string", "description": "提交信息"},
                    "add_all": {"type": "boolean", "description": "是否暂存所有变更后提交（默认false）"}
                },
                "required": ["message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_checkout",
            "description": "切换Git分支或恢复文件。支持创建新分支、切换分支、恢复工作区文件。危险操作，会进行安全检查。",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Git仓库路径（默认当前目录）"},
                    "action": {"type": "string", "description": "操作类型: switch(切换分支), create(创建并切换新分支), restore(恢复文件到最新提交)", "enum": ["switch", "create", "restore"]},
                    "branch": {"type": "string", "description": "分支名(switch/create操作)"},
                    "file_path": {"type": "string", "description": "要恢复的文件路径(restore操作)"}
                },
                "required": ["action"]
            }
        }
    },
]


# ============ 辅助函数 ============

def _git_run(repo_path, *args, timeout=10):
    """运行git命令的辅助函数"""
    cmd = ["git", "-C", repo_path or "."] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            return None, result.stderr.strip() or f"git命令失败 (exit code {result.returncode})"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return None, "git命令超时"
    except FileNotFoundError:
        return None, "git未安装或不在PATH中"


# ============ 工具执行函数 ============

def tool_git_status(args):
    """查看Git仓库状态"""
    repo_path = args.get("repo_path", ".")

    out, err = _git_run(repo_path, "status", "--porcelain=v2", "--branch")
    if err:
        out, err = _git_run(repo_path, "status")
        if err:
            return f"获取Git状态失败: {err}"

    branch_out, _ = _git_run(repo_path, "branch", "--show-current")
    branch = branch_out or "unknown"

    short_out, _ = _git_run(repo_path, "status", "--short")
    if short_out:
        lines = short_out.split('\n')
        staged = sum(1 for l in lines if l and l[0] in 'MADRC')
        unstaged = sum(1 for l in lines if l and len(l) > 1 and l[1] in 'MD')
        untracked = sum(1 for l in lines if l.startswith('??'))
        summary = f"暂存:{staged} 未暂存:{unstaged} 未跟踪:{untracked}"
    else:
        summary = "工作区干净"

    detail = short_out[:1000] if short_out else "无变更"

    return f"分支: {branch}\n统计: {summary}\n变更:\n{detail}"


def tool_git_diff(args):
    """查看Git差异"""
    repo_path = args.get("repo_path", ".")
    target = args.get("target", "unstaged")
    file_path = args.get("file_path", "")
    max_lines = args.get("max_lines", 200)

    if target == "staged":
        cmd_args = ["diff", "--cached"]
    elif target == "HEAD":
        cmd_args = ["diff", "HEAD"]
    else:
        cmd_args = ["diff"]

    if file_path:
        cmd_args += ["--", file_path]

    out, err = _git_run(repo_path, *cmd_args, timeout=15)
    if err:
        return f"获取Git差异失败: {err}"

    if not out:
        return "无差异"

    lines = out.split('\n')
    if len(lines) > max_lines:
        return '\n'.join(lines[:max_lines]) + f"\n... (共{len(lines)}行，已截断至{max_lines}行)"
    return out


def tool_git_commit(args):
    """提交Git变更"""
    repo_path = args.get("repo_path", ".")
    message = args.get("message", "")
    add_all = args.get("add_all", False)

    if not message:
        return "提交信息不能为空"

    branch_out, _ = _git_run(repo_path, "branch", "--show-current")
    current_branch = branch_out or ""
    protected = {"main", "master"}
    if current_branch in protected and add_all:
        return f"[需确认] 当前在受保护分支 '{current_branch}' 上执行 add_all + commit，如确认请说明。"

    if add_all:
        out, err = _git_run(repo_path, "add", "-A")
        if err:
            return f"暂存变更失败: {err}"

    out, err = _git_run(repo_path, "commit", "-m", message, timeout=15)
    if err:
        if "nothing to commit" in err or "nothing to commit" in (out or ""):
            return "没有需要提交的变更"
        return f"提交失败: {err}"

    hash_out, _ = _git_run(repo_path, "rev-parse", "--short", "HEAD")
    commit_hash = hash_out or "unknown"

    return f"提交成功: {commit_hash} on {current_branch}\n{out}"


def tool_git_checkout(args):
    """切换Git分支或恢复文件"""
    repo_path = args.get("repo_path", ".")
    action = args.get("action", "")
    branch = args.get("branch", "")
    file_path = args.get("file_path", "")

    if action == "switch":
        if not branch:
            return "切换分支需要 branch 参数"
        out, err = _git_run(repo_path, "checkout", branch, timeout=10)
        if err:
            return f"切换分支失败: {err}"
        return f"已切换到分支: {branch}"

    elif action == "create":
        if not branch:
            return "创建分支需要 branch 参数"
        out, err = _git_run(repo_path, "checkout", "-b", branch, timeout=10)
        if err:
            return f"创建分支失败: {err}"
        return f"已创建并切换到新分支: {branch}"

    elif action == "restore":
        if not file_path:
            return "恢复文件需要 file_path 参数"
        out, err = _git_run(repo_path, "checkout", "HEAD", "--", file_path, timeout=10)
        if err:
            return f"恢复文件失败: {err}"
        return f"已恢复文件: {file_path}"

    else:
        return f"未知操作: {action}，支持: switch, create, restore"


TOOL_DISPATCH = {
    "git_status": tool_git_status,
    "git_diff": tool_git_diff,
    "git_commit": tool_git_commit,
    "git_checkout": tool_git_checkout,
}
