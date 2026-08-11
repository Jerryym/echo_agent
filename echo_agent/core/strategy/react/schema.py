from typing import Annotated, Literal

from pydantic import Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState
from ...model.message import Message, append_messages
from ..strategy_task import StrategyTask
from .observation import Observation, append_observations


class ReActInput(BaseInput):
    """
    ReAct 输入模型
    
    参数：
        task：任务
        conversation：当前任务的对话上下文
    """
    task: StrategyTask = Field(description="任务")
    conversation: list[Message] = Field(description="当前任务的对话上下文")


class ReActState(BaseState):
    """
    ReAct 状态模型

    参数:
        task: 任务
        conversation: 对话上下文
        reasoning: 推理结果
        task_status: 任务状态
            in_progress: 进行中
            human_in_the_loop: 需要人类干预
            no_tool_calls: 没有工具调用
            invalid_tools: 无效的工具
            completed: 完成
            cancelled: 取消
            failed: 失败
        observations: 观察
        trajectory: 轨迹列表
        step_count: 步数
        retry_count: 当前 ReAct 执行过程中，因异常（no_tool_calls、invalid_tools）导致重新尝试的次数。
    """
    task: StrategyTask = Field(default_factory=StrategyTask)
    conversation: list[Message] = Field(default_factory=list)
    reasoning: str = ""
    task_status: Literal["in_progress", "human_in_the_loop", "no_tool_calls", "invalid_tools", "completed", "cancelled", "failed"] = "in_progress"
    observations: Annotated[list[Observation], append_observations] = Field(default_factory=list)
    trajectory: Annotated[list[Message], append_messages] = Field(default_factory=list)
    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)


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
        max_steps: 最大推理步数
        retry_max_count: 最大重试次数
    """
    max_steps: int = Field(default=20)
    retry_max_count: int = Field(default=3)
