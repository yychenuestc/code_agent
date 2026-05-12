# -*- coding: utf-8 -*-
"""
Hook拦截器 - 安全检查 + 操作确认
借鉴 Claude Code 的 Hook 系统：独立于Agent的安全层，强制拦截危险操作

SQL 安全检查已移至外部 skill（check_sql_safety）
"""
from core.config import (
    DANGEROUS_PYTHON_PATTERNS, DANGEROUS_JAVA_PATTERNS,
    FILE_WRITE_CONFIRM_THRESHOLD, CONFIDENCE_THRESHOLD
)


class HookResult:
    """Hook检查结果"""
    def __init__(self, allowed=True, message="", needs_confirm=False, confirm_message=""):
        self.allowed = allowed
        self.message = message
        self.needs_confirm = needs_confirm
        self.confirm_message = confirm_message


def check_python_safety(code):
    """
    PreToolUse Hook: Python代码安全检查
    拦截危险操作，返回 HookResult
    """
    hits = []
    for pattern in DANGEROUS_PYTHON_PATTERNS:
        if pattern in code:
            hits.append(pattern)

    if hits:
        return HookResult(
            allowed=False,
            message=f"安全拦截: 检测到危险操作 {hits}。如需执行，请确认安全性后手动操作。"
        )

    # 检查是否需要确认（如包含文件写入操作）
    confirm_patterns = ["open(", "write("]
    confirm_hits = [p for p in confirm_patterns if p in code]
    if confirm_hits:
        return HookResult(
            allowed=True,
            needs_confirm=True,
            confirm_message=f"代码包含文件操作 {confirm_hits}，确认执行？"
        )

    return HookResult(allowed=True)


# check_sql_safety 已移至外部 skill
# 由 skill 内部提供，不再在此文件中定义


def check_java_safety(code):
    """PreToolUse Hook: Java代码安全检查"""
    hits = []
    for pattern in DANGEROUS_JAVA_PATTERNS:
        if pattern in code:
            hits.append(pattern)

    if hits:
        return HookResult(
            allowed=False,
            message=f"安全拦截: 检测到危险操作 {hits}"
        )

    return HookResult(allowed=True)


def check_file_write_safety(file_path, content):
    """PreToolUse Hook: 文件写入安全检查"""
    # 检查是否写入关键系统文件
    dangerous_paths = ["/etc/", "/usr/", "C:\\Windows\\", "C:\\Program Files\\"]
    for dp in dangerous_paths:
        if file_path.startswith(dp):
            return HookResult(
                allowed=False,
                message=f"安全拦截: 禁止写入系统目录 {dp}"
            )

    # 大文件写入需确认
    content_size = len(content.encode('utf-8')) if content else 0
    if content_size > FILE_WRITE_CONFIRM_THRESHOLD:
        size_kb = content_size / 1024
        return HookResult(
            allowed=True,
            needs_confirm=True,
            confirm_message=f"写入文件较大 ({size_kb:.1f}KB)，确认写入？"
        )

    return HookResult(allowed=True)


def filter_review_issues(issues):
    """
    置信度过滤：只保留高置信度的审查结果
    借鉴 Claude Code code-review 插件的设计
    """
    high_confidence = []
    for issue in issues:
        confidence = issue.get("confidence", 0)
        if confidence >= CONFIDENCE_THRESHOLD:
            high_confidence.append(issue)
    return high_confidence
