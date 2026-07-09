from typing import Any

from pydantic import BaseModel, Field   


class ToolDefinition(BaseModel):
    """
    工具定义

    Args:
        name: 工具名称
        description: 工具描述
        parameters: 参数
    """
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """
    工具调用

    Args:
        name: 工具名称
        args: 工具参数
        tool_call_id: 工具调用ID
    """
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


class ToolResult(BaseModel):
    """
    工具执行结果

    Args:
        result: 工具执行结果数据
        success: 工具执行是否成功
    """
    result: Any = None
    success: bool = False