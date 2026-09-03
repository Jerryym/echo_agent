from typing import Any

from pydantic import BaseModel, Field

from ..model.tool import ToolCall
from ..model.token_usage import TokenUsage


class LLMResult(BaseModel):
    """
    LLM 原始响应承接模型

    参数:
        text: 响应内容
        reasoning: 推理内容
        tool_calls: 工具调用
        raw: 原始响应
        structured: 结构化响应
        response_metadata: 响应元数据
        token_usage: 词元使用情况
    """
    text: str = Field(default="")
    reasoning: str | None = Field(default=None)
    tool_calls: list[ToolCall] | None = Field(default_factory=list)
    raw: Any = None
    structured: dict[str, Any] | None = None
    response_metadata: dict[str, Any] | None = None
    token_usage: TokenUsage
