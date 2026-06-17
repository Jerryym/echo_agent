from typing import Optional
from pydantic import BaseModel


class LLMConfig(BaseModel):
    """
    大模型配置

    参数:
        base_url: 模型地址
        api_key: 模型API KEY
        model_name: 模型名称
        model_provider: 模型提供方(如: openai, Anthropic, google, ...)
        temperature: 温度
        max_tokens: 最大token数
        timeout: 超时时间
        max_retries: 最大重试次数
    """    
    base_url: str
    api_key: str
    model_name: str
    model_provider: Optional[str] = "openai"
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: int = 1200
    max_retries: int = 3