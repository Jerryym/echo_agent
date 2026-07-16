from enum import Enum
from typing import Any, Literal

from pydantic import Field

from ...graph import BaseInput, BaseOutput, BaseState


class HITLType(str, Enum):
    """
    HITL类型
    """
    INPUT = "input"
    APPROVAL = "approval"


class HITLInput(BaseInput):
    """
    HITL输入
    """
    type: HITLType
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HITLState(BaseState):
    """
    HITL状态
    """
    id: str = ""
    type: HITLType
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "waiting", "completed", "cancelled"] = "pending"
    result: dict[str, Any] | None = None


class HITLOutput(BaseOutput):
    """
    HITL输出
    """
    id: str
    status: Literal["completed", "cancelled"]
    result: dict[str, Any] = Field(default_factory=dict)
