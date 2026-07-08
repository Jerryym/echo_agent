from typing import Any

from pydantic import Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState


class ReActInput(BaseInput):
    """
    ReAct 输入模型

    参数:
        input: 输入
    """
    input: dict[str, Any]


class ReActState(BaseState):
    """
    ReAct 状态模型

    参数:
        input: 输入
        reasoning: 推理
        observations: 观察结果列表
        step_count: 步数
        response: 响应
    """
    reasoning: str
    observations: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    response: str


class ReActOutput(BaseOutput):  
    """
    ReAct 输出模型

    参数:
        response: 响应
    """
    response: str


class ReActContext(BaseContext):
    """
    ReAct 上下文模型

    参数:
        max_steps: 最大步数
        tool_list: 工具列表
    """
    max_steps: int = Field(default=3)
    tool_list: list[dict[str, Any]] = Field(default_factory=list)