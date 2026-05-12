# -*- coding: utf-8 -*-
"""
Agent 状态定义与结构化输出模型
LangGraph StateGraph 的核心状态 + Pydantic 结构化输出
"""
from typing import TypedDict, Annotated, Literal, Optional
from operator import add
from pydantic import BaseModel, Field


# ============ LangGraph 状态 ============

class AgentState(TypedDict, total=False):
    """LangGraph 全局状态，节点间通过此结构传递数据"""
    # 消息历史（累加模式）
    messages: Annotated[list, add]
    # 用户原始输入
    user_input: str
    # 任务分类
    task_type: Literal["analyze", "develop", "review", "chat"]
    # 项目上下文
    project_path: str
    language: str  # python / sql / java
    # 探索阶段
    exploration_result: Optional[dict]
    # 设计阶段
    design_options: Optional[list]
    chosen_design_index: Optional[int]
    # 实现阶段
    implementation: Optional[dict]
    implementation_error: Optional[str]
    # 验证阶段
    verify_result: Optional[dict]
    # 审查阶段
    review_issues: Optional[list]
    # 最终输出
    final_output: str
    # 重试计数
    iteration: int


# ============ 结构化输出模型 ============

class EntryPoint(BaseModel):
    """项目入口点"""
    file: str = Field(description="文件路径")
    line: int = Field(description="行号")
    type: str = Field(description="入口类型: main/web/test/script")


class ExplorationResult(BaseModel):
    """项目探索结果"""
    language: str = Field(description="主要编程语言")
    framework: str = Field(default="", description="检测到的框架")
    build_tool: str = Field(default="", description="构建工具")
    entry_points: list[EntryPoint] = Field(default_factory=list, description="入口点列表")
    key_files: list[str] = Field(default_factory=list, description="关键文件列表（5-10个）")
    patterns: list[str] = Field(default_factory=list, description="发现的设计模式/约定")
    observations: list[str] = Field(default_factory=list, description="观察到的优缺点")
    summary: str = Field(description="项目概要描述")


class DesignOption(BaseModel):
    """设计方案"""
    name: str = Field(description="方案名称")
    approach: str = Field(description="核心理念")
    files_to_modify: list[str] = Field(description="需要修改/新增的文件")
    key_structure: str = Field(description="关键代码结构描述")
    pros: list[str] = Field(description="优点")
    cons: list[str] = Field(description="缺点")
    complexity: Literal["简单", "中等", "复杂"] = Field(description="实现复杂度")


class DesignResult(BaseModel):
    """多方案设计结果"""
    options: list[DesignOption] = Field(description="设计方案列表（3个）")
    recommended: int = Field(description="推荐方案索引（0-based）")
    reason: str = Field(description="推荐理由")


class ReviewIssue(BaseModel):
    """代码审查问题"""
    dimension: Literal["简洁性", "正确性", "规范性"] = Field(description="审查维度")
    severity: Literal["CRITICAL", "IMPORTANT", "MINOR"] = Field(description="严重等级")
    confidence: int = Field(ge=0, le=100, description="置信度（0-100）")
    location: str = Field(default="", description="文件位置 file:line")
    message: str = Field(description="问题描述")
    suggestion: str = Field(default="", description="修复建议")


class ReviewResult(BaseModel):
    """代码审查结果"""
    issues: list[ReviewIssue] = Field(description="审查问题列表（仅置信度>=80）")
    overall_assessment: str = Field(description="总体评价")
    score: int = Field(ge=0, le=100, description="代码质量评分（0-100）")


class TaskClassification(BaseModel):
    """任务分类结果"""
    task_type: Literal["analyze", "develop", "review", "chat"] = Field(
        description="任务类型: analyze=分析项目, develop=开发任务, review=代码审查, chat=普通对话"
    )
    language: str = Field(default="", description="编程语言: python/sql/java，无法判断则为空")
    confidence: int = Field(ge=0, le=100, description="分类置信度")
