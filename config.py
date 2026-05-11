# -*- coding: utf-8 -*-
"""Dev Agent 配置文件"""

# DeepSeek API配置（请替换为你自己的 API Key）
API_KEY = "xxx"
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

# 代码执行限制
PYTHON_TIMEOUT = 30          # Python代码执行超时（秒）
JAVA_TIMEOUT = 60            # Java编译运行超时（秒）
MAX_OUTPUT_LENGTH = 5000     # 最大输出长度

# Hook安全配置
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
