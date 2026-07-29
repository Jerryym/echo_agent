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


class HITLOutput(BaseModel):
    """
    HITL输出
    """
    id: str
    status: Literal["completed", "cancelled"]
    result: dict[str, Any] = Field(default_factory=dict)


class HITLState(BaseModel):
    """
    HITL状态

    Args:
        request: Human-in-the-loop 请求
        response: Human-in-the-loop 响应
    """
    request: HITLInput | None = None
    response: HITLOutput | None = None
