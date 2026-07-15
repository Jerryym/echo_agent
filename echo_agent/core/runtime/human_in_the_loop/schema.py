from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class HITLType(str, Enum):
    """
    HITL类型
    """
    INPUT = "input"
    APPROVAL = "approval"


class HITLInput(BaseModel):
    """
    HITL输入
    """
    type: HITLType
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)


class HITLState(BaseModel):
    """
    HITL状态
    """
    id: str
    type: HITLType
    status: Literal["pending", "waiting", "completed", "cancelled"]
    result: dict[str, Any] | None = None


class HITLOutput(BaseModel):
    """
    HITL输出
    """
    id: str
    status: Literal["completed", "cancelled"]
    result: dict[str, Any] = Field(default_factory=dict)
