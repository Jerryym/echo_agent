from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from ....graph import Node
from ....graph.schema import BaseContext
from ..schema import HITLState, HITLType


class ApprovalFlow(Node):
    """
    ApprovalFlow节点
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
        # 中断并等待用户批准或拒绝
        response = interrupt(
            {
                "id": state.id,
                "type": state.type.value,
                "description": state.input.description,
                "payload": state.input.payload,
            }
        )
        return {
            "status": "completed",
            "result": response,
        }
