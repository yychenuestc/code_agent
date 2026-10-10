# -*- coding: utf-8 -*-
"""
LLM 封装层 - 多模型适配（DeepSeek / GLM 等 OpenAI 兼容 API）
支持多模型切换、结构化输出（通过 function calling）、流式响应
"""
import json
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, ValidationError
import core.config as config


def get_llm(model: str = None, temperature: float = 0, streaming: bool = False) -> BaseChatModel:
    """
    获取 LLM 实例

    Args:
        model: 模型名称或别名（fast/strong/default/preset名），None 则用配置默认值
        temperature: 温度参数
        streaming: 是否启用流式输出

    说明：所有配置均从 core.config 动态读取，因此 Web 界面在运行期更新 API Key 后，
    下一次调用 get_llm() 新建的实例会立即使用新 Key。
    """
    # 支持通过 preset 名切换（如 "deepseek", "glm"）
    if model and model in config.MODEL_CONFIGS:
        preset = config.MODEL_CONFIGS[model]
        return ChatOpenAI(
            base_url=preset["base_url"],
            api_key=preset["api_key"],
            model=preset["model"],
            temperature=temperature,
            streaming=streaming,
        )

    aliases = {"fast": "deepseek-chat", "strong": "deepseek-reasoner", "default": config.MODEL}
    model_name = aliases.get(model, model or config.MODEL)

    return ChatOpenAI(
        base_url=config.BASE_URL,
        api_key=config.API_KEY,
        model=model_name,
        temperature=temperature,
        streaming=streaming,
    )


def _pydantic_to_function_schema(pydantic_model: type[BaseModel]) -> dict:
    """将 Pydantic 模型转换为 OpenAI function calling 的工具定义格式"""
    schema = pydantic_model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": pydantic_model.__name__,
            "description": pydantic_model.__doc__ or f"输出{pydantic_model.__name__}结构",
            "parameters": schema,
        },
    }


def get_structured_llm(
    pydantic_model: type[BaseModel],
    model: str = None,
    temperature: float = 0,
    max_retries: int = 1,
) -> "StructuredLLM":
    """
    获取支持结构化输出的 LLM 实例（通过 function calling）

    DeepSeek/GLM 均不支持 response_format 的 JSON schema，
    因此通过 function calling 实现结构化输出。

    Args:
        pydantic_model: Pydantic 模型类，用于约束输出结构
        model: 模型名称或别名
        temperature: 温度参数
        max_retries: 校验失败时携带纠错提示重试的次数（默认 1 次）

    Returns:
        StructuredLLM 实例，调用 .invoke() 返回解析后的 Pydantic 对象
    """
    llm = get_llm(model=model, temperature=temperature)
    return StructuredLLM(llm, pydantic_model, max_retries=max_retries)


class StructuredLLM:
    """
    通过 function calling 实现结构化输出
    兼容 DeepSeek / GLM 等不支持 response_format 的 API

    校验策略：
    1. 优先解析 tool_calls；无则尝试从文本内容中抽取 JSON。
    2. 若解析/校验失败且仍有重试次数，则把「JSON Schema + 具体错误 + 上次输出」
       作为纠错提示追加到对话，再请求一次，引导模型返回符合预期的结构。
    3. 重试用尽后再做最终兜底（返回默认值，仍失败则抛出最后一次错误）。
    """

    def __init__(self, llm: BaseChatModel, pydantic_model: type[BaseModel], max_retries: int = 1):
        self.llm = llm
        self.pydantic_model = pydantic_model
        self.function_schema = _pydantic_to_function_schema(pydantic_model)
        self.max_retries = max(0, int(max_retries))

    def _extract_data(self, response):
        """从响应中提取候选数据（dict），返回 (data_or_None, raw_for_prompt)"""
        if getattr(response, "tool_calls", None):
            args = response.tool_calls[0].get("args")
            return args, args
        content = getattr(response, "content", "") or ""
        if content:
            try:
                c = content
                if "```json" in c:
                    c = c.split("```json")[1].split("```")[0]
                elif "```" in c:
                    c = c.split("```")[1].split("```")[0]
                return json.loads(c.strip()), content
            except (json.JSONDecodeError, Exception):
                return None, content
        return None, content

    def _correction_prompt(self, error, raw) -> str:
        """构造纠错提示：带上 schema 与具体错误，引导模型重新按格式输出"""
        schema = json.dumps(self.function_schema["function"]["parameters"], ensure_ascii=False)
        return (
            "你上一次的输出不符合要求的数据结构，请修正后重试。\n"
            f"错误信息: {error}\n"
            f"你上次返回的内容: {str(raw)[:300]}\n"
            f"请严格通过调用函数 `{self.pydantic_model.__name__}` 返回结果，"
            "只填充下面 JSON Schema 中定义的字段，所有必填字段都不能缺失，类型要匹配：\n"
            f"{schema}"
        )

    def invoke(self, messages, **kwargs):
        """调用 LLM 并返回解析后的 Pydantic 对象（带结构校验与纠错重试）"""
        llm_with_func = self.llm.bind_tools([self.function_schema], tool_choice="auto")
        attempt_messages = list(messages)
        last_error = None

        for attempt in range(self.max_retries + 1):
            response = llm_with_func.invoke(attempt_messages, **kwargs)
            data, raw = self._extract_data(response)

            if data is not None:
                try:
                    return self.pydantic_model.model_validate(data)
                except ValidationError as e:
                    last_error = e
            else:
                last_error = ValueError("模型未返回可解析的结构化数据（无 tool_calls 也无有效 JSON）")

            # 仍有重试机会：追加纠错提示，引导模型重新输出
            if attempt < self.max_retries:
                attempt_messages = attempt_messages + [
                    HumanMessage(content=self._correction_prompt(last_error, raw))
                ]

        # 重试用尽：最终兜底（部分 schema 无必填字段时可成功）
        try:
            return self.pydantic_model.model_validate({})
        except ValidationError:
            raise last_error


# ============ 嵌入模型（RAG 向量化）============

class _LocalEmbeddings:
    """本地 sentence-transformers 嵌入，暴露 LangChain Embeddings 风格接口。

    仅在 ACTIVE_EMBEDDING == "local" 或在线 API 不可用时作为兜底使用。
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed_documents(self, texts):
        model = self._load()
        return model.encode(list(texts), show_progress_bar=False, batch_size=32).tolist()

    def embed_query(self, text):
        model = self._load()
        return model.encode([text], show_progress_bar=False)[0].tolist()


def get_embeddings(provider: str = None):
    """获取嵌入器（LangChain Embeddings 接口：embed_documents / embed_query）。

    Args:
        provider: "api"（OpenAI 兼容 Embedding API）或 "local"（本地模型）。
                  None 时读取 core.config.ACTIVE_EMBEDDING。

    默认走在线 Embedding API；若依赖缺失或未配置，可显式使用 "local" 回退。
    """
    provider = provider or config.ACTIVE_EMBEDDING

    if provider == "local":
        cfg = config.EMBEDDING_CONFIGS["local"]
        return _LocalEmbeddings(cfg["model"])

    # 默认：OpenAI 兼容 Embedding API
    from langchain_openai import OpenAIEmbeddings
    cfg = config.EMBEDDING_CONFIGS["api"]
    return OpenAIEmbeddings(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        # 非 OpenAI 官方端点不做 tiktoken 长度校验，避免不兼容
        check_embedding_ctx_length=False,
    )
