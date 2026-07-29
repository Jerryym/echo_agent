from typing import Annotated, Any

from pydantic import BaseModel, Field

from ..model import (
    HITLInput,
    HITLOutput,
    Message,
    ToolCall,
    ToolResult,
    UserInput,
    append_messages,
)


class BaseInput(BaseModel):
    """
    Graph 输入模型

    参数:
        input: 输入
    """
    input: UserInput | dict[str, Any] | str


class BaseOutput(BaseModel):
    """
    Graph 输出模型
    """
    pass


class BaseState(BaseModel):
    """
    Graph 状态模型

    参数:
        input: 输入
        messages: 消息列表
        tool_calls: 工具调用列表
        tool_results: 工具执行结果列表
        hitl_request: HITL 请求
        hitl_response: HITL 响应
        response: 响应
    """
    input: UserInput | dict[str, Any] | str | None = None
    messages: Annotated[list[Message], append_messages] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    hitl_request: HITLInput | None = None
    hitl_response: HITLOutput | None = None
    response: str | None = None


class BaseContext(BaseModel):
    """
    Graph 上下文模型
    """
    pass
