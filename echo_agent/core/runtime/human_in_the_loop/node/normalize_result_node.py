from typing import Any, Literal

from langchain_core.runnables import RunnableConfig

from ....graph import Node
from ....graph.schema import BaseContext
from ....model import HITLType
from ..schema import HITLState


class NormalizeResultNode(Node):
    """
    NormalizeResultNode节点，用于规范化结果

    按 HITLType + resume result 二次解析 status，避免 Flow 误写导致
    cancelled 不可达或审批拒绝被当成 completed。
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: HITLState, context: BaseContext | None = None, config: RunnableConfig | None = None) -> dict:
        result = state.result if isinstance(state.result, dict) else {}
        return {
            "id": state.id,
            "status": self._resolve_status(state.type, result),
            "result": result,
        }

    async def arun(
        self,
        state: HITLState,
        context: BaseContext | None = None,
        config: RunnableConfig | None = None,
    ) -> dict:
        raise NotImplementedError("NormalizeResultNode is sync-only")

    def _resolve_status(
        self,
        hitl_type: HITLType,
        result: dict[str, Any],
    ) -> Literal["completed", "cancelled"]:
        """按 HITLType 对 resume result 二次裁定最终 status。"""
        if hitl_type == HITLType.APPROVAL:
            return self._resolve_approval_status(result)
        if hitl_type == HITLType.INPUT:
            return self._resolve_input_status(result)
        return "cancelled"

    def _resolve_approval_status(self, result: dict[str, Any]) -> Literal["completed", "cancelled"]:
        if result.get("status") == "cancelled" or result.get("cancelled") is True:
            return "cancelled"
        if result.get("approved") is True:
            return "completed"
        return "cancelled"

    def _resolve_input_status(self, result: dict[str, Any]) -> Literal["completed", "cancelled"]:
        if result.get("status") == "cancelled" or result.get("cancelled") is True:
            return "cancelled"
        if "values" in result:
            return "completed"
        return "cancelled"
