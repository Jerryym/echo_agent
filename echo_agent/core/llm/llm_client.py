from typing import Any, Dict, List, Optional

from langchain.chat_models import init_chat_model
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

    def invoke(self, prompt: str, user_input: UserInput, history: Optional[List[Dict[Any, Any]]] = None,  tool_list: Optional[List[Dict[str, str]]] = None):
        """
        调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
        """
        try:
            # 构建输入消息
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
            )
            # 添加工具列表
            if tool_list is not None and len(tool_list) > 0:
                self._model.bind_tools(tool_list)
            # 调用模型
            response = self._model.invoke(messages)
            # 解析响应
            return self._parse_response(response)
        except LLMException:
            raise
        except Exception as e:
            raise LLMInvokeError(
                message="LLM invoke failed",
                detail=str(e)
            )

    def stream(self, prompt: str, user_input: UserInput, history: Optional[List[Dict[Any, Any]]] = None,  tool_list: Optional[List[Dict[str, str]]] = None):
        """
        流式调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
        """
        try:
            # 构建输入消息
            messages = self._build_messages(
                prompt=prompt,
                user_input=user_input,
                history=history or [],
            )
            # 添加工具列表
            if tool_list is not None and len(tool_list) > 0:
                self._model.bind_tools(tool_list)
            # 调用模型
            for chunk in self._model.stream(messages):
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
        model = init_chat_model(
            model=self._config.model_name,# 模型名称
            model_provider=self._config.model_provider,# 模型提供方
            api_key=self._config.api_key,# 模型API KEY
            base_url=self._config.base_url,# 模型地址
            temperature=self._config.temperature,# 模型温度
            max_tokens=self._config.max_tokens,# 最大Tokens
            timeout=self._config.timeout,# 超时时间
            max_retries=self._config.max_retries,# 最大重试次数
        )
        return model

    def _build_messages(self, prompt: str, user_input: UserInput, history: List[Dict[Any, Any]]):
        """
        构建 LangChain Messages
        """
        messages: List[BaseMessage] = []

        # system prompt
        messages.append(SystemMessage(content=prompt))
        # history
        messages.extend(self._build_history(history))
        # user input
        messages.append(HumanMessage(content=user_input.text))
        return messages

    def _build_history(self, history: List[Dict[Any, Any]]):
        """
        构建历史消息
        """
        if not history:
            return []

        result: List[BaseMessage] = []
        for msg in history:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            elif role == "system":
                result.append(SystemMessage(content=content))

        return result

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