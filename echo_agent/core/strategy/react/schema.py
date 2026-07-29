from typing import Annotated, Literal, Sequence

from pydantic import Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState
from ...model import Message, append_messages


class ReActInput(BaseInput):
    """
    ReAct 输入模型

    参数:
        messages: 消息列表
    """
    messages: Sequence[Message] = Field(default_factory=list)


class ReActState(BaseState):
    """
    ReAct 状态模型

    参数:
        reasoning: 推理
        task_status: 任务状态
            in_progress: 进行中
            human_in_the_loop: 需要人类干预
            no_tool_calls: 没有工具调用
            completed: 完成
            cancelled: 取消
            failed: 失败
        observations: 观察
        step_count: 步数
        retry_count: 重试次数
    """
    reasoning: str = ""
    task_status: Literal["in_progress", "human_in_the_loop", "no_tool_calls", "completed", "cancelled", "failed"] = "in_progress"
    observations: list[dict] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)


class ReActOutput(BaseOutput):
    """
    ReAct 输出模型

    参数:
        response: 响应
        messages: 消息列表
    """
    response: str
    messages: list[Message] = Field(default_factory=list)


class ReActContext(BaseContext):
    """
    ReAct 上下文模型

    参数:
        max_steps: 最大推理步数
        retry_max_count: 最大重试次数
    """
    max_steps: int = Field(default=10)
    retry_max_count: int = Field(default=3)
