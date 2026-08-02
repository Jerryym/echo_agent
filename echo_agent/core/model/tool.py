from pydantic import BaseModel, Field
from typing import Any


class ToolCall(BaseModel):
    """
    工具调用

    Args:
        name: 工具名称
        args: 工具参数
        tool_call_id: 工具调用ID
        missing_args: 缺少的参数列表
    """
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str
    missing_args: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """
    工具执行结果

    Args:
        name: 工具名称
        success: 工具执行是否成功
        result: 工具执行结果
        error: 工具执行错误信息, 当success为False时有效
        tool_call_id: 工具调用ID, 同对应ToolCall的tool_call_id
    """
    name: str
    success: bool = False
    result: Any = None
    error: str | None = None
    tool_call_id: str


class ToolState(BaseModel):
    """
    工具状态

    Args:
        tool_calls: 工具调用列表
        tool_results: 工具执行结果列表
    """
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
