from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ReasoningConfig(BaseModel):
    """
    思考模式配置

    参数:
        effort: 思考强度
    """
    effort: Literal["none", "low", "high", "max"] | None = None


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

        parallel_tool_calls: 是否并行调用工具
        builtin_tools: 模型/provider 内置工具列表，由调用方按模型能力传入

        use_responses_api: 是否使用 Responses API
        output_version: AIMessage 输出版本（如 responses/v1）
        reasoning: 思考模式配置

        extra_body: provider 扩展请求参数（如 enable_thinking）
        default_headers: 默认请求头
    """
    # 基础连接配置
    base_url: str
    api_key: str
    model_name: str
    model_provider: Optional[str] = "openai"

    # 模型生成配置
    temperature: float = 0.2
    max_tokens: int = 1024

    # 请求与重试配置
    timeout: int = 1200
    max_retries: int = 3

    # 工具调用配置
    parallel_tool_calls: bool = True
    builtin_tools: list[dict[str, Any]] = Field(default_factory=list)

    # Responses API 配置
    use_responses_api: bool = False
    output_version: Optional[str] = None
    reasoning: ReasoningConfig | None = None

    # Provider 扩展配置
    extra_body: dict[str, Any] = Field(default_factory=dict)
    default_headers: dict[str, str] = Field(default_factory=dict)
