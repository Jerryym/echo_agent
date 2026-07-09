from typing import Any, Optional, Sequence

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from ..model import UserInput

from .exception import (
    LLMException,
    LLMInitializeError,
    LLMInvokeError,
    LLMResponseDecodeError,
)
from .llm_config import LLMConfig
from .llm_result import LLMResult


class LLMClient:
    """
    大模型客户端

    参数:
        config: 模型配置
        model: 模型实例
    """
    def __init__(self, config: LLMConfig):
        try:
            self._config = config
            self._model = self._initialize_model()
        except Exception as e:
            raise LLMInitializeError(
                message="LLM model initialize failed",
                detail=str(e)
            )

    def invoke(self, prompt: str, user_input: UserInput | dict | str, history: Optional[Sequence[BaseMessage]] = None, tool_list: Optional[list[dict[str, Any]]] = None):
        """
        调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
            )
            # 绑定工具
            model = self._model
            if tool_list:
                model = model.bind_tools(tool_list)
            # 调用模型
            response = model.invoke(messages)
            # 解析响应
            return self._parse_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(message="LLM invoke failed", detail=str(e))

    def stream(self, prompt: str, user_input: UserInput | dict | str, history: Optional[Sequence[BaseMessage]] = None, tool_list: Optional[list[dict[str, Any]]] = None):
        """
        流式调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
        """
        try:
            # 构建 Messages
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
            )
            # 绑定工具
            model = self._model
            if tool_list:
                model = model.bind_tools(tool_list)
            # 解析响应
            for chunk in model.stream(messages):
                yield self._parse_response(chunk)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM stream invoke failed",
                detail=str(e)
            )

    def _initialize_model(self):
        """初始化模型"""
        if self._config.model_provider == "openai":
            model_kwargs: dict[str, Any] = {
                "model": self._config.model_name,
                "api_key": self._config.api_key,
                "base_url": self._config.base_url,
                "temperature": self._config.temperature,
                "max_tokens": self._config.max_tokens,
                "timeout": self._config.timeout,
                "max_retries": self._config.max_retries,
                "use_responses_api": self._config.use_responses_api,
            }
            if self._config.output_version:
                model_kwargs["output_version"] = self._config.output_version
            if self._config.extra_body:
                model_kwargs["extra_body"] = self._config.extra_body
            # 初始化模型
            model = ChatOpenAI(**model_kwargs)
            # 绑定内置工具
            if self._config.builtin_tools:
                model = model.bind(tools=self._config.builtin_tools)
        else:
            raise LLMInitializeError(
                message="model provider not supported",
                detail=f"model provider {self._config.model_provider} not supported"
            )
        return model

    def _build_messages(self, prompt: str, user_input: UserInput | dict, history: Sequence[BaseMessage]):
        """
        构建 LangChain Messages
        """
        messages: list[BaseMessage] = []

        messages.append(SystemMessage(content=prompt))
        messages.extend(history)
        if isinstance(user_input, UserInput):
            messages.append(user_input.to_human_message())
        elif isinstance(user_input, dict) or isinstance(user_input, str):
            messages.append(HumanMessage(content=user_input))
        return messages

    def _parse_response(self, response: AIMessage):
        """
        解析 LLM 响应
        """
        try:
            content = self._normalize_content(response.content)
            return LLMResult(
                    content=content,
                    tool_calls=getattr(response, "tool_calls", None),
                    raw=response,
                    response_metadata=getattr(response, "response_metadata", None),
                )
        except Exception as e:
            raise LLMResponseDecodeError(
                message="parse llm response failed",
                detail=str(e)
            )

    def _normalize_content(self, content: Any):
        """
        规范化内容
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "".join(parts)
        return str(content) if content is not None else ""
