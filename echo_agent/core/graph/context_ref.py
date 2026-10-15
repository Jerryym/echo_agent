from typing import Annotated, Any

from pydantic import PlainValidator

from ..model.agent import AgentResult
from ..model.session import SessionState
from ..model.skill import SkillRuntimeContext
from ..model.workflow import WorkflowTask


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


def _preserve_workflow_tasks_dict(value: Any) -> dict[str, WorkflowTask]:
    """
    保留当前 Turn 的工作流任务字典引用
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"workflow_tasks must be a dict, got {type(value)!r}")
    return value


def _preserve_session_state(value: Any) -> SessionState:
    """Keep the same SessionState instance across Context construction."""
    if isinstance(value, SessionState):
        return value
    if isinstance(value, dict):
        return SessionState.model_validate(value)
    raise TypeError(f"session_state must be SessionState, got {type(value)!r}")


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

# Turn-scoped mutable workflow tasks; must retain object identity across Parent/Strategy Context.
WorkflowTasksMap = Annotated[
    dict[str, WorkflowTask],
    PlainValidator(_preserve_workflow_tasks_dict),
]

# Session-scoped mutable state; must retain object identity across Parent/Strategy Context.
SessionStateRef = Annotated[
    SessionState,
    PlainValidator(_preserve_session_state),
]

# Turn-scoped mutable result; must retain object identity across Parent/Strategy Context.
AgentResultRef = Annotated[
    AgentResult | None,
    PlainValidator(_preserve_agent_result),
]
