from typing import Any
from pydantic import BaseModel, Field

from ..tool import ToolCall


class LLMResult(BaseModel):
    """
    LLM 原始响应承接模型

    参数:
        content: 响应内容
        tool_calls: 工具调用
        raw: 原始响应
        structured: 结构化响应
        response_metadata: 响应元数据
    """
    content: str = Field(default="")
    tool_calls: list[ToolCall] | None = Field(default_factory=list)
    raw: Any = None
    structured: BaseModel | dict[str, Any] | None = None
    response_metadata: dict[str, Any] | None = None
