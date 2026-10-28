from typing import Any

from pydantic import BaseModel, Field

from ..model.agent import AgentResources
from ..model.context import ContextState
from ..model.hitl import HITLInteraction
from ..model.input import UserInput
from ..model.tool import ToolState
from ..model.step import Step
from .context_ref import (
    ActiveSkillsMap,
    AgentResultRef,
    SessionStateRef,
    WorkflowTasksMap,
)


class BaseInput(BaseModel):
    """
    Graph 输入模型

    参数:
        context: 上下文状态
    """
    steps: list[Step] = Field(default_factory=list)
    current_step: Step | None = None

    context: ContextState = Field(default_factory=ContextState)


class BaseOutput(BaseModel):
    """
    Graph 输出模型

    参数:
        context: 上下文状态
    """
    steps: list[Step] = Field(default_factory=list)
    current_step: Step | None = None

    context: ContextState = Field(default_factory=ContextState)


class BaseState(BaseModel):
    """
    Graph 状态模型

    参数:
        input: 输入
        response: 响应
        context: 上下文状态
        steps: 本轮模型交互步骤，按执行顺序保存
        current_step: 当前正在进行的模型交互步骤
        tool_state: 工具状态
        hitl_state: HITL状态
    """
    input: UserInput | dict[str, Any] | str | None = None
    response: str | None = None
    context: ContextState = Field(default_factory=ContextState)

    steps: list[Step] = Field(default_factory=list)
    current_step: Step | None = None

    tool_state: ToolState = Field(default_factory=ToolState)
    hitl_state: HITLInteraction = Field(default_factory=HITLInteraction)


class BaseContext(BaseModel):
    """
    Graph 上下文模型

    参数:
        session_state: 会话运行时状态
        resources: 静态资源目录（system_prompt / skill_list / kb_list）
        active_skills: 已加载 Skill（会话级可变 dict，构造时保持同一引用）
        workflow_tasks: 工作流任务（Turn级可变 dict，构造时保持同一引用）
        agent_result: 本轮交互的顶层输出（运行中由节点增量写入）
    """
    session_state: SessionStateRef
    resources: AgentResources = Field(default_factory=AgentResources)
    active_skills: ActiveSkillsMap = Field(default_factory=dict)
    workflow_tasks: WorkflowTasksMap = Field(default_factory=dict)
    agent_result: AgentResultRef = None
