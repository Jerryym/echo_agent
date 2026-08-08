from typing import Any, Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from .....common import get_logger
from ....graph import Node
from ....graph.schema import BaseContext
from ..schema import HITLState

logger = get_logger("hitl.approval")


class ApprovalFlow(Node):
    """
    ApprovalFlow节点
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, runtime: Runtime[BaseContext], config: RunnableConfig | None = None) -> dict:
        hitl_id = state.id or str(uuid4())  
        # 中断并等待用户批准或拒绝
        response = interrupt(
            {
                "id": hitl_id,
                "type": state.type.value,
                "description": state.description,
                "payload": state.payload,
            }
        )
        logger.info("response=%s", response)

        result = response if isinstance(response, dict) else {"raw": response}
        return {
            "id": hitl_id,
            "status": self._resolve_status(response),
            "result": result,
        }

    async def arun(self, state: HITLState, runtime: Runtime[BaseContext]) -> dict:
        return self.run(state, runtime)

    def _resolve_status(self, response: Any) -> Literal["completed", "cancelled"]:
        """
        APPROVAL resume 协议：
          completed: {"approved": true}
          cancelled: {"approved": false} / 显式取消 / 非法载荷
        """
        if not isinstance(response, dict):
            return "cancelled"
        if response.get("status") == "cancelled" or response.get("cancelled") is True:
            return "cancelled"
        if response.get("approved") is True:
            return "completed"
        return "cancelled"
