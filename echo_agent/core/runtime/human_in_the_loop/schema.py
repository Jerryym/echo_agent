from typing import Any, Literal

from pydantic import Field

from ...graph.schema import BaseState
from ...model.hitl import HITLType


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
