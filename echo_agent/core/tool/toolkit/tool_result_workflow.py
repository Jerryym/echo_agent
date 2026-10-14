from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.config import get_config
from langgraph.pregel import Pregel
from langgraph.runtime import get_runtime

from ...capability.workflow.tool_result.schema import (
    ToolResultAnalyseInput,
    ToolResultAnalyseResult,
)
from ...model.conversation import ConversationContextItem, ConversationContextType
from ...model.tool import ToolResultItem


def create_trigger_tool_result_analyse_tool(workflow: Pregel) -> BaseTool:
    """创建 Tool Result 分析工作流触发工具"""

    @tool
    async def trigger_tool_result_analyse(tool_call_id: str, requirement: str) -> dict[str, Any]:
        """
        Analyse a previously executed tool result.

        Use this tool when information from a previous tool
        execution is needed but its complete result is not
        available in the conversation context.

        The workflow reads the stored result incrementally,
        extracts relevant information, and stops when the
        requirement is satisfied or all content is processed.

        Args:
            tool_call_id: ID of the previous tool execution.
            requirement: Information to extract from its result.

        Returns:
            Extracted information and whether the entire
            tool result has been processed.
        """
        runtime = get_runtime()
        if runtime.context is None:
            raise RuntimeError("Tool result runtime context is not available")

        result_item = _resolve_tool_result_item(tool_call_id, runtime.context.session_state.context_items)
        result = await workflow.ainvoke(
            ToolResultAnalyseInput(
                result_item=result_item,
                requirement=requirement,
            ),
            config=get_config(),
            context=runtime.context,
        )

        validated = ToolResultAnalyseResult.model_validate(result)
        return validated.model_dump(mode="json")

    trigger_tool_result_analyse.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }

    return trigger_tool_result_analyse


def _resolve_tool_result_item(tool_call_id: str, context_items: list[ConversationContextItem]) -> ToolResultItem:
    item_id = f"tool_result:{tool_call_id}"
    for item in context_items:
        if (item.id == item_id and item.type == ConversationContextType.TOOL_RESULT):
            return ToolResultItem.model_validate(item.content)
    raise LookupError(f"Tool result not found: {tool_call_id}")
