from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ....graph import Node
from ....graph.schema import BaseContext
from ..schema import HITLState


class ApprovalFlow(Node):
    """
    ApprovalFlow节点
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
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
        print("[ApprovalFlow] response:", response)

        return {
            "id": hitl_id,
            "status": "completed",
            "result": response,
        }
