from langchain_core.runnables import RunnableConfig

from ....graph import Node
from ....graph.schema import BaseContext
from ..schema import HITLState, HITLOutput


class NormalizeResultNode(Node):
    """
    NormalizeResultNode节点，用于规范化结果
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
        output = HITLOutput(
            id=state.id,
            status=self._normalize_status(state),
            result=state.result,
        )
        return {
            "response": output.model_dump(),
        }

    def _normalize_status(self, state: HITLState) -> str:
        if state.status == "completed":
            return "completed"
        return "cancelled"
