from typing import Annotated, Literal

from pydantic import BaseModel, Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState
from ...model.context import ContextState
from ...model.message import Message, append_messages
from ..strategy_task import StrategyTask
from .observation import Observation, append_observations


def build_react_history(context: ContextState) -> list[Message]:
    """工作消息是模型历史的唯一来源，轨迹仅用于执行记录。"""
    return [message.model_copy(deep=True) for message in context.messages]


class ReActInput(BaseInput):
    """
    ReAct 输入模型
    
    参数：
        task：任务
    """
    task: StrategyTask = Field(description="任务")


class ReActState(BaseState):
    """
    ReAct 状态模型

    参数:
        task: 任务
        assessment: 当前任务进展判断
        next_action: 下一步执行意图
        tool_list: 工具列表, 用于指导ActionNode节点绑定工具
        task_status: 任务状态
            in_progress: 进行中
            human_in_the_loop: 需要人类干预
            no_tool_calls: 没有工具调用
            invalid_tools: 无效的工具
            blocked: 阻塞-用于权限验证失败等场景
            completed: 完成
            cancelled: 取消
            failed: 失败
        observations: 观察
        trajectory: 轨迹列表
        step_count: 步数
        retry_count: 当前 ReAct 执行过程中，因异常（no_tool_calls、invalid_tools）导致重新尝试的次数
        duplicate_fingerprint_count：记录重复指纹评估单元的累计次数
        duplicate_fingerprint_clear_count：记录连续正常指纹评估单元的次数
    """
    task: StrategyTask = Field(default_factory=StrategyTask)
    assessment: str = ""
    next_action: str = ""
    tool_list: list[str] = Field(default_factory=list)
    task_status: Literal[
        "in_progress", 
        "human_in_the_loop", 
        "no_tool_calls", 
        "invalid_tools", 
        "blocked", 
        "completed", 
        "cancelled", 
        "failed",
    ] = "in_progress"
    observations: Annotated[list[Observation], append_observations] = Field(default_factory=list)
    trajectory: Annotated[list[Message], append_messages] = Field(default_factory=list)

    step_count: int = Field(default=0)
    retry_count: int = Field(default=0)
    duplicate_fingerprint_count: int = Field(default=0)
    duplicate_fingerprint_clear_count: int = Field(default=0)


class ReActOutput(BaseOutput):
    """
    ReAct 输出模型

    参数:
        response: 响应
        trajectory: 轨迹列表
    """
    response: str
    trajectory: list[Message] = Field(default_factory=list)


class ReActContext(BaseContext):
    """
    ReAct 上下文模型

    参数:
        fingerprint_window_size: 指纹评估窗口大小
        retry_max_count: 最大重试次数
        duplicate_fingerprint_max_count: 最大重复指纹评估单元次数
        duplicate_fingerprint_reset_threshold: 连续正常指纹评估单元次数阈值
    """
    fingerprint_window_size: int = Field(default=20)
    retry_max_count: int = Field(default=3)
    duplicate_fingerprint_max_count: int = Field(default=3, gt=0)
    duplicate_fingerprint_reset_threshold: int = Field(default=5, gt=0)


# ---------------------------------------------------------------------------
# 结构化输出
# ---------------------------------------------------------------------------

class ReasonStructuredOutput(BaseModel):
    """
    Reason节点结构化输出：任务推进判断、下一步执行决策与循环控制

    参数:
        assessment: 评估
        next_action: 下一步操作
        tool_list: 工具列表
        task_status: 任务状态
    """
    assessment: str = Field(
        description=(
            "Concise assessment of the task's current progress, "
            "completed work, remaining requirements, and available "
            "results that can be used immediately."
        )
    )
    next_action: str = Field(
        description=(
            "The single next operation that best advances the task, "
            "derived from the current progress assessment. "
            "This field is consumed by ActionNode. "
            "Do not include tool names or tool arguments."
        )
    )
    tool_list: list[str] = Field(
        default_factory=list,
        description=(
            "Available tool names required to perform the next operation. "
            "Do not include tool arguments."
        )
    )
    task_status: Literal["in_progress", "completed"] = Field(
        description=(
            "Whether further execution is required. "
            "Use 'completed' only when the objective has been satisfied "
            "with sufficient evidence."
        )
    )
