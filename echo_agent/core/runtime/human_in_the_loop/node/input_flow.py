from typing import Any, Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ....graph import Node
from ....graph.schema import BaseContext
from ..schema import HITLState


class InputFlow(Node):
    """
    InputFlow节点，用于处理用户输入
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
        hitl_id = state.id or str(uuid4())
        # 中断并等待用户输入
        response = interrupt(
            {
                "id": hitl_id,
                "type": state.type.value,
                "description": state.description,
                "payload": state.payload,
            }
        )
        print("[InputFlow] response:", response)

        result = response if isinstance(response, dict) else {"raw": response}
        return {
            "id": hitl_id,
            "status": self._resolve_status(response),
            "result": result,
        }

    def _resolve_status(self, response: Any) -> Literal["completed", "cancelled"]:
        """
        INPUT resume 协议：
          completed: {"values": {...}}
          cancelled: {"cancelled": true} / {"status": "cancelled"} / 非法载荷
        """
        if not isinstance(response, dict):
            return "cancelled"
        if response.get("status") == "cancelled" or response.get("cancelled") is True:
            return "cancelled"
        if "values" in response:
            return "completed"
        return "cancelled"
