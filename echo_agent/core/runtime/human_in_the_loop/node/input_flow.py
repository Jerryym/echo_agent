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

        return {
            "id": hitl_id,
            "status": "completed",
            "result": response,
        }
