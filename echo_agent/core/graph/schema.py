from typing import Any

from pydantic import BaseModel, Field

from ..model.agent import AgentResources
from ..model.conversation import ConversationState
from ..model.hitl import HITLInteraction
from ..model.input import UserInput
from ..model.tool import ToolState
from .context_ref import ActiveSkillsMap, AgentResultRef, SessionStateRef, WorkflowTasksMap


class BaseInput(BaseModel):
    """
    Graph 输入模型

    参数:
        conversation: 会话状态
    """
    conversation: ConversationState = Field(default_factory=ConversationState)


class BaseOutput(BaseModel):
    """
    Graph 输出模型

    参数:
        conversation: 会话状态
    """
    conversation: ConversationState = Field(default_factory=ConversationState)


class BaseState(BaseModel):
    """
    Graph 状态模型

    参数:
        input: 输入
        response: 响应
        conversation: 会话状态
        tool: 工具状态
        hitl: HITL状态
    """
    input: UserInput | dict[str, Any] | str | None = None
    response: str | None = None
    conversation: ConversationState = Field(default_factory=ConversationState)

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
