from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainValidator

from ..model.agent import AgentResources, AgentResult, AgentState
from ..model.hitl import HITLInteraction
from ..model.input import UserInput
from ..model.skill import SkillRuntimeContext
from ..model.tool import ToolState


def _preserve_active_skills_dict(value: Any) -> dict[str, SkillRuntimeContext]:
    """
    Keep the same dict instance across Context construction.

    Default Pydantic dict[str, Model] validation rebuilds a new dict, which
    breaks session-level active_skills persistence across HITL interrupt/resume
    (load_skill writes to a copy that is discarded when the invoke ends).
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"active_skills must be a dict, got {type(value)!r}")
    return value


def _preserve_agent_result(value: Any) -> AgentResult | None:
    """Keep the same AgentResult instance across Context construction."""
    if value is None:
        return None
    if isinstance(value, AgentResult):
        return value
    if isinstance(value, dict):
        return AgentResult.model_validate(value)
    raise TypeError(f"agent_result must be AgentResult | None, got {type(value)!r}")


# Session-scoped mutable map; must retain object identity.
ActiveSkillsMap = Annotated[
    dict[str, SkillRuntimeContext],
    PlainValidator(_preserve_active_skills_dict),
]

# Turn-scoped mutable result; must retain object identity across Parent/Strategy Context.
AgentResultRef = Annotated[
    AgentResult | None,
    PlainValidator(_preserve_agent_result),
]


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
        response: 响应
        tool: 工具状态
        hitl: HITL状态
    """
    input: UserInput | dict[str, Any] | str | None = None
    response: str | None = None

    tool_state: ToolState = Field(default_factory=ToolState)
    hitl_state: HITLInteraction = Field(default_factory=HITLInteraction)


class BaseContext(BaseModel):
    """
    Graph 上下文模型

    参数:
        agent_state: 智能体状态
        resources: 静态资源目录（system_prompt / skill_list / kb_list）
        active_skills: 已加载 Skill（会话级可变 dict，构造时保持同一引用）
        agent_result: 本轮交互的顶层输出（运行中由节点增量写入）
    """
    agent_state: AgentState
    resources: AgentResources = Field(default_factory=AgentResources)
    active_skills: ActiveSkillsMap = Field(default_factory=dict)
    agent_result: AgentResultRef = None
