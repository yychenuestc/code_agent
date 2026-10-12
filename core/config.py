# -*- coding: utf-8 -*-
"""Code Agent 配置文件"""
import os
import json

# ============ 持久化根目录 & 密钥存储 ============
# 所有持久化产物（向量库、会话检查点、密钥）统一落在 PERSIST_ROOT 下。
# 可用环境变量 CODE_AGENT_PERSIST_ROOT 覆盖，默认在项目根目录的 .cache/。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSIST_ROOT = os.environ.get(
    "CODE_AGENT_PERSIST_ROOT", os.path.join(_PROJECT_ROOT, ".cache")
)
# 运行期在 Web 界面配置的密钥持久化到此文件（.cache 已被 .gitignore 忽略）
SECRETS_PATH = os.path.join(PERSIST_ROOT, "secrets.json")


def _load_secrets() -> dict:
    """读取本地持久化的密钥配置，不存在/损坏则返回空 dict。"""
    try:
        with open(SECRETS_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


_SECRETS = _load_secrets()


def _resolve_key(env_name: str, secret_key: str, default: str) -> str:
    """密钥优先级：本地 secrets.json > 环境变量 > 默认占位。"""
    if _SECRETS.get(secret_key):
        return _SECRETS[secret_key]
    return os.environ.get(env_name, default)


# ============ 多模型配置 ============
# 预设模型配置，切换 ACTIVE_MODEL 即可更换 LLM 后端
# API Key 优先级：Web 界面保存的 secrets.json > 环境变量 > 默认占位
MODEL_CONFIGS = {
    "deepseek": {
        "api_key": _resolve_key("DEEPSEEK_API_KEY", "deepseek_api_key", "your-deepseek-api-key"),
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    "glm": {
        "api_key": _resolve_key("GLM_API_KEY", "glm_api_key", "your-zhipu-api-key"),
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.1",
    },
}

# 当前使用的模型（修改此值切换模型: "deepseek" 或 "glm"）
ACTIVE_MODEL = _SECRETS.get("active_model", "deepseek")

# 自动导出当前模型的配置（其他模块通过 core.config.API_KEY 动态读取）
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

# ============ 持久化 & 中间件配置 ============
# PERSIST_ROOT / SECRETS_PATH 已在文件顶部定义。

# --- 向量库（Chroma，持久化到本地磁盘）---
VECTOR_DB_DIR = os.path.join(PERSIST_ROOT, "chroma")   # Chroma PersistentClient 数据目录
VECTOR_TOP_K = 10                                       # 默认召回条数
VECTOR_MIN_SCORE = 0.1                                  # 余弦相似度最低阈值
CHUNK_SIZE = 50                                         # 代码分块行数
CHUNK_OVERLAP = 10                                      # 分块重叠行数

# --- 会话记忆持久化（LangGraph SqliteSaver）---
CHECKPOINT_DB_PATH = os.path.join(PERSIST_ROOT, "checkpoints.sqlite")

# --- 嵌入模型配置 ---
# 默认走 OpenAI 兼容的 Embedding API（与主 LLM 一样用 API，不需本地下载模型）。
# 若无可用 Embedding API，可将 ACTIVE_EMBEDDING 设为 "local"，回退到本地 sentence-transformers。
EMBEDDING_CONFIGS = {
    "api": {
        # 兼容 OpenAI /embeddings 协议的服务端点。DeepSeek 暂无 embedding，
        # 默认用智谱 GLM 的 embedding-3；也可换成 OpenAI text-embedding-3-small 等。
        "base_url": os.environ.get("EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        "api_key": os.environ.get("EMBEDDING_API_KEY", os.environ.get("GLM_API_KEY", "your-embedding-api-key")),
        "model": os.environ.get("EMBEDDING_MODEL", "embedding-3"),
    },
    "local": {
        "model": os.environ.get("LOCAL_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"),
    },
}
# "api" = 在线 Embedding API（默认）；"local" = 本地 sentence-transformers
ACTIVE_EMBEDDING = os.environ.get("CODE_AGENT_EMBEDDING", "api")


# ============ 运行期密钥配置（供 Web 界面调用）============

def _save_secrets():
    os.makedirs(PERSIST_ROOT, exist_ok=True)
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(_SECRETS, f, ensure_ascii=False, indent=2)


_ENV_NAME = {"deepseek": "DEEPSEEK_API_KEY", "glm": "GLM_API_KEY"}


def set_model_api_key(api_key: str, provider: str = "deepseek", persist: bool = True) -> None:
    """运行期更新某个模型后端的 API Key，并（可选）持久化到 secrets.json。

    同时更新 MODEL_CONFIGS、os.environ，以及当 provider 为当前激活模型时的模块级
    API_KEY；因 core.llm 动态读取 core.config，后续新建的 LLM 会立即使用新 Key。
    """
    global API_KEY
    if provider not in MODEL_CONFIGS:
        raise ValueError(f"未知的模型后端: {provider}")
    api_key = (api_key or "").strip()
    MODEL_CONFIGS[provider]["api_key"] = api_key
    if provider in _ENV_NAME:
        os.environ[_ENV_NAME[provider]] = api_key
    if provider == ACTIVE_MODEL:
        API_KEY = api_key
    if persist:
        _SECRETS[f"{provider}_api_key"] = api_key
        _save_secrets()


def _mask(secret: str) -> str:
    """脱敏显示：仅保留首尾各 4 位，占位符视为未配置。"""
    s = str(secret or "")
    if not s or s.startswith("your-"):
        return ""
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def get_config_status() -> dict:
    """返回脱敏后的配置状态，供 Web 界面展示（绝不返回明文密钥）。"""
    status = {"active_model": ACTIVE_MODEL, "providers": {}}
    for name, cfg in MODEL_CONFIGS.items():
        key = cfg.get("api_key", "")
        status["providers"][name] = {
            "configured": bool(key) and not str(key).startswith("your-"),
            "masked": _mask(key),
            "model": cfg.get("model", ""),
            "base_url": cfg.get("base_url", ""),
        }
    return status
