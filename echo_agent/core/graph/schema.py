from typing import Annotated, Sequence

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from ..model import UserInput


class BaseInput(BaseModel):
    """
    Graph 输入模型

    参数:
        input: UserInput 用户输入
    """
    input: UserInput


class BaseOutput(BaseModel):
    """
    Graph 输出模型
    """
    pass


class BaseState(BaseModel):
    """
    Graph 状态模型

    参数:
        input: UserInput 用户输入
        messages: 消息列表
    """
    input: UserInput
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)


class BaseContext(BaseModel):
    """
    Graph 上下文模型
    """
    pass