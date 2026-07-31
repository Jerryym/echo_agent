from typing import Any

from pydantic import BaseModel, Field

from ..model import (
    HITLInteraction,
    ToolState,
    UserInput,
    AgentState,
)
from ..trace import AgentTrace


class BaseInput(BaseModel):
    """
    Graph 输入模型
    """
    pass


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
        # messages: 消息列表
        # tool_calls: 工具调用列表
        # tool_results: 工具执行结果列表
        # hitl_request: HITL 请求
        # hitl_response: HITL 响应
        response: 响应
        tool: 工具状态
        hitl: HITL状态
    """
    input: UserInput | dict[str, Any] | str | None = None
    # messages: Annotated[list[Message], append_messages] = Field(default_factory=list)
    # tool_calls: list[ToolCall] = Field(default_factory=list)
    # tool_results: list[ToolResult] = Field(default_factory=list)
    # hitl_request: HITLInput | None = None
    # hitl_response: HITLOutput | None = None
    response: str | None = None

    tool_state: ToolState = Field(default_factory=ToolState)
    hitl_state: HITLInteraction = Field(default_factory=HITLInteraction)


class BaseContext(BaseModel):
    """
    Graph 上下文模型

    参数:
        agent_state: 智能体状态
        trace: 智能体跟踪
    """
    agent_state: AgentState
    trace: AgentTrace | None = None
