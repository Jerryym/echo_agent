from enum import Enum
from typing import Any

from pydantic import BaseModel, Field   


class ToolType(str, Enum):
    """
    工具类型
    """
    FUNCTION = "function"
    HTTP = "http"
    MCP = "mcp"


class ToolDefinition(BaseModel):
    """
    工具定义

    Args:
        name: 工具名称
        description: 工具描述
        parameters: 参数
        type: 工具类型
    """
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    type: ToolType = ToolType.FUNCTION


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
        name: 工具名称
        result: 工具执行结果
        success: 工具执行是否成功
        tool_call_id: 工具调用ID, 同对应ToolCall的tool_call_id
    """
    name: str
    result: Any = None
    success: bool = False
    tool_call_id: str