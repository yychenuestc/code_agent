# -*- coding: utf-8 -*-
"""
LLM 封装层 - 多模型适配（DeepSeek / GLM 等 OpenAI 兼容 API）
支持多模型切换、结构化输出（通过 function calling）、流式响应
"""
import json
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel
from config import API_KEY, BASE_URL, MODEL, MODEL_CONFIGS


# 模型别名映射
MODEL_ALIASES = {
    "fast": "deepseek-chat",
    "strong": "deepseek-reasoner",
    "default": MODEL,
}


def get_llm(model: str = None, temperature: float = 0, streaming: bool = False) -> BaseChatModel:
    """
    获取 LLM 实例

    Args:
        model: 模型名称、别名（fast/strong/default）或 preset 名（deepseek/glm），None 则用配置默认值
        temperature: 温度参数
        streaming: 是否启用流式输出
    """
    # 支持通过 preset 名切换（如 "deepseek", "glm"）
    if model and model in MODEL_CONFIGS:
        preset = MODEL_CONFIGS[model]
        return ChatOpenAI(
            base_url=preset["base_url"],
            api_key=preset["api_key"],
            model=preset["model"],
            temperature=temperature,
            streaming=streaming,
        )

    model_name = MODEL_ALIASES.get(model, model or MODEL)

    return ChatOpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
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
) -> "StructuredLLM":
    """
    获取支持结构化输出的 LLM 实例（通过 function calling）

    DeepSeek/GLM 均不支持 response_format 的 JSON schema，
    因此通过 function calling 实现结构化输出。

    Args:
        pydantic_model: Pydantic 模型类，用于约束输出结构
        model: 模型名称或别名
        temperature: 温度参数

    Returns:
        StructuredLLM 实例，调用 .invoke() 返回解析后的 Pydantic 对象
    """
    llm = get_llm(model=model, temperature=temperature)
    return StructuredLLM(llm, pydantic_model)


class StructuredLLM:
    """
    通过 function calling 实现结构化输出
    兼容 DeepSeek / GLM 等不支持 response_format 的 API
    """

    def __init__(self, llm: BaseChatModel, pydantic_model: type[BaseModel]):
        self.llm = llm
        self.pydantic_model = pydantic_model
        self.function_schema = _pydantic_to_function_schema(pydantic_model)

    def invoke(self, messages, **kwargs):
        """调用 LLM 并返回解析后的 Pydantic 对象"""
        # 使用 tool_choice="auto" 以兼容 DeepSeek/GLM
        llm_with_func = self.llm.bind_tools(
            [self.function_schema],
            tool_choice="auto",
        )

        response = llm_with_func.invoke(messages, **kwargs)

        # 从 tool_calls 中提取参数
        if response.tool_calls:
            tc = response.tool_calls[0]
            args = tc["args"]
            return self.pydantic_model.model_validate(args)

        # 降级：尝试从文本内容中解析 JSON
        if response.content:
            try:
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                data = json.loads(content.strip())
                return self.pydantic_model.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        # 最终降级：返回默认值
        return self.pydantic_model.model_validate({})
