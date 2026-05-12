# -*- coding: utf-8 -*-
"""Code Agent 配置文件"""
import os

# ============ 多模型配置 ============
# 预设模型配置，切换 ACTIVE_MODEL 即可更换 LLM 后端
# API Key 优先从环境变量读取，未设置则使用默认值
MODEL_CONFIGS = {
    "deepseek": {
        "api_key": os.environ.get("DEEPSEEK_API_KEY", "your-deepseek-api-key"),
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "glm": {
        "api_key": os.environ.get("GLM_API_KEY", "your-zhipu-api-key"),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.1",
    },
}

# 当前使用的模型（修改此值切换模型: "deepseek" 或 "glm"）
ACTIVE_MODEL = "deepseek"

# 自动导出当前模型的配置（其他模块 import API_KEY/BASE_URL/MODEL 即可）
_current = MODEL_CONFIGS[ACTIVE_MODEL]
API_KEY = _current["api_key"]
BASE_URL = _current["base_url"]
MODEL = _current["model"]

# ============ 代码执行限制 ============
PYTHON_TIMEOUT = 30          # Python代码执行超时（秒）
JAVA_TIMEOUT = 60            # Java编译运行超时（秒）
MAX_OUTPUT_LENGTH = 5000     # 最大输出长度

# ============ Hook安全配置 ============
DANGEROUS_PYTHON_PATTERNS = [
    "os.system", "os.remove", "os.rmdir", "shutil.rmtree",
    "subprocess.call", "subprocess.Popen",
    "__import__", "importlib", "exec(", "eval(",
    "open(", "write(", "os.unlink",
]

DANGEROUS_JAVA_PATTERNS = [
    "Runtime.exec", "ProcessBuilder", "System.exit",
    "File.delete", "Files.delete",
]

# 文件操作确认阈值（超过此大小需确认，字节）
FILE_WRITE_CONFIRM_THRESHOLD = 50000

# 置信度过滤阈值
CONFIDENCE_THRESHOLD = 80

# ============ 外部 Skill 配置 ============
# Skill 配置按 skill 名称索引，由 skill_loader 加载时注入到对应 skill 模块
# 添加新 skill 配置只需在此字典中新增条目
SKILL_CONFIGS = {}

# 向后兼容
BIGDA_SQL_CONFIG = SKILL_CONFIGS.get("bigda_sql", {})
