from typing import Annotated, Any, Literal, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState
from ...model import UserInput


class ReActInput(BaseInput):
    """
    ReAct 输入模型

    参数:
        input: 输入
        messages: 消息列表
    """
    input: UserInput | dict[str, Any] | str
    messages: Sequence[BaseMessage] = []


class ReActState(BaseState):
    """
    ReAct 状态模型

    参数:
        reasoning: 推理
        information_status: 信息状态
        observations: 观察结果列表
        step_count: 步数
        retry_count: 重试次数
        is_finished: 是否完成
    """
    reasoning: str = ""
    information_status: Literal["sufficient","insufficient"] = "insufficient"
    observations: list[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    is_finished: bool = Field(default=False)


class ReActOutput(BaseOutput):
    """
    ReAct 输出模型

    参数:
        response: 响应
        messages: 消息列表
    """
    response: str
    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)


class ReActContext(BaseContext):
    """
    ReAct 上下文模型

    参数:
        max_steps: 最大推理步数
        retry_max_count: 最大重试次数
    """
    max_steps: int = Field(default=10)
    retry_max_count: int = Field(default=3)
