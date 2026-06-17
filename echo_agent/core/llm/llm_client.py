from typing import Any

from langchain.chat_models import init_chat_model

from llm_config import LLMConfig


class LLMClient:
    """
    大模型客户端

    参数:
        config: 模型配置
        model: 模型实例
    """
    def __init__(self, config: LLMConfig):
        self._config = config
        self._model = self._initialize_model()

    def invoke(self, prompt: str, user_input: str, history: list[dict[Any, Any]]=None, tool_list: list[dict[str, str]]=None):
        """
        调用模型

        参数:
            prompt: 提示语
            user_input: 用户输入
            history: 历史记录
            tool_list: 工具列表
        """
        pass

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
