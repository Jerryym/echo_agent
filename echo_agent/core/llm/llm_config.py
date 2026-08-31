from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """
    大模型配置

    参数:
        base_url: 模型地址
        api_key: 模型 API KEY
        model_name: 模型名称
        model_provider: 模型提供方（如 openai、anthropic、google 等）
        temperature: 温度
        max_tokens: 最大 token 数
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        use_responses_api: 是否使用 Responses API
        output_version: AIMessage 输出版本（如 responses/v1）
        builtin_tools: 模型/provider 内置工具列表，由调用方按模型能力传入
        extra_body: provider 扩展请求参数（如 enable_thinking）
        default_headers: 默认请求头
    """
    base_url: str
    api_key: str
    model_name: str
    model_provider: Optional[str] = "openai"
    temperature: float = 0.2
    max_tokens: int = 1024
    timeout: int = 1200
    max_retries: int = 3
    use_responses_api: bool = False
    output_version: Optional[str] = None
    builtin_tools: list[dict[str, Any]] = Field(default_factory=list)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    default_headers: dict[str, str] = Field(default_factory=dict)
