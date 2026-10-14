from typing import Annotated, Any, Literal

from langchain.tools import tool
from pydantic import BaseModel, Field

from ...graph import BaseContext, BaseInput, BaseOutput, BaseState
from ...model.conversation import ConversationState
from ...model.message import Message, Role, append_messages
from ..strategy_task import StrategyTask
from .observation import Observation, append_observations


def build_react_history(conversation: ConversationState, trajectory: list[Message]) -> list[Message]:
    """读取会话摘要和消息，再追加本轮轨迹"""
    history: list[Message] = []
    if conversation.summary is not None:
        history.append(Message(role=Role.SYSTEM, content=conversation.summary.render()))
    history.extend(conversation.messages)
    history.extend(trajectory)
    return history


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
        reasoning: 推理结果
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
        retry_count: 当前 ReAct 执行过程中，因异常（no_tool_calls、invalid_tools）导致重新尝试的次数。
    """
    task: StrategyTask = Field(default_factory=StrategyTask)
    reasoning: str = ""
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
        max_steps: 最大推理步数
        retry_max_count: 最大重试次数
    """
    max_steps: int = Field(default=20)
    retry_max_count: int = Field(default=3)


# ---------------------------------------------------------------------------
# 结构化输出
# ---------------------------------------------------------------------------

class ReasonStructuredOutput(BaseModel):
    """
    Reason节点结构化输出

    参数:
        thought: 思考结果，面向调试和可观测性的思考过程
        reasoning: 执行推理结果，用于指导下一步执行
        tool_list: 下一步执行所需的工具名称列表
        task_status: 任务状态，用于驱动 ReAct 流程
        continue_reasoning: 是否继续推理
    """
    thought: str = Field(
        description=(
            "A concise description of the reasoning process used to analyze "
            "the current task. This field is intended for tracing, debugging, "
            "and runtime visualization only. It is not used for tool selection "
            "or execution."
        )
    )
    reasoning: str = Field(
        description=(
            "A structured execution-oriented reasoning result describing the "
            "operation or capability that should be performed next. This output "
            "will be consumed by the Action node to generate tool calls. "
            "Do not include tool names, tool parameters, or tool call arguments."
        )
    )
    tool_list: list[str] = Field(
        default_factory=list,
        description=(
            "A list of tool names required for the next execution step. "
            "Only select names from the available tool name list. "
            "This field represents required capabilities, not final tool calls. "
            "Do not include parameters."
        )
    )
    task_status: Literal["in_progress", "completed"] = Field(
        description=(
            "Reason-owned lifecycle signal only. "
            "Allowed values: 'in_progress' | 'completed'. "
            "Do NOT output human_in_the_loop, no_tool_calls, invalid_tools, "
            "cancelled, or failed (those are set by Action/runtime). "
            "'in_progress': the user objective is not yet achieved; further "
            "execution is required. Put the next required operation in "
            "'reasoning' and identify the required tools in 'tool_list'. "
            "'completed': the user objective has been achieved AND confirmed "
            "by the current-step observations and/or by tool messages already "
            "present in conversation history. Do not require observations to "
            "repeat tool-message payloads. "
            "If neither channel confirms the objective, you MUST use "
            "'in_progress' even when a conversational reply seems sufficient—"
            "Final, not Reason, produces the user-facing answer. "
            "Never mark 'completed' because Action produced no tool calls; "
            "that signal is handled by runtime status, not by this field."
        )
    )
    continue_reasoning: bool = Field(
        description=(
            "Whether ReasonNode requires additional internal Workflow execution. "
            "When true, task_status must be 'in_progress', tool_list must be empty, "
            "and reasoning must describe the additional internal analysis required. "
            "ReasonNode will select and execute the Workflow in a separate model "
            "call. Set false when the result can be returned to the outer ReAct graph."
        )
    )
