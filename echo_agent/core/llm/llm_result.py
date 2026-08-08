from typing import Any

from pydantic import BaseModel, Field

from ..model.tool import ToolCall
from ..trace import TokenUsage


class LLMResult(BaseModel):
    """
    LLM 原始响应承接模型

    参数:
        content: 响应正文（text / 多模态占位等，不含模型 reasoning block）
        reasoning: 模型侧推理/思考原文（content block type=reasoning），可供前端展示；与 ReActState.reasoning（策略层执行导向摘要）不同
        tool_calls: 工具调用
        raw: 原始响应
        structured: 结构化响应
        response_metadata: 响应元数据
        token_usage: 词元使用情况
    """
    content: str = Field(default="")
    reasoning: str = Field(default="")
    tool_calls: list[ToolCall] | None = Field(default_factory=list)
    raw: Any = None
    structured: BaseModel | dict[str, Any] | None = None
    response_metadata: dict[str, Any] | None = None
    token_usage: TokenUsage
