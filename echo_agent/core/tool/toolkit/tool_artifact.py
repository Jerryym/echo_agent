from typing import Any

from langchain_core.tools import BaseTool, tool
from langgraph.config import get_config
from langgraph.runtime import get_runtime

from ...capability.workflow.tool_artifact import (
    ToolArtifactAnalyseInput,
    ToolArtifactAnalyseResult,
)


def create_trigger_tool_artifact_analyse_tool(workflow) -> BaseTool:
    """创建 Tool Artifact 分析工作流触发工具"""

    @tool
    async def trigger_tool_artifact_analyse(tool_call_id: str, requirement: str, offset: int = 0) -> dict[str, Any]:
        """
        Analyse a large tool result stored as an artifact.

        Use this tool when a previous tool result was too large to include
        directly in the conversation and was stored as an artifact.

        The tool processes one bounded artifact chunk per call. If completed
        is false, call the tool again with next_offset as offset to continue.

        Args:
            tool_call_id: ID of the tool call that produced the artifact.
            requirement: Information to extract from the artifact.
            offset: Byte offset from which analysis should continue.

        Returns:
            Extracted content, the next byte offset, and whether processing
            has reached the end of the artifact.
        """
        runtime = get_runtime()
        if runtime.context is None:
            raise RuntimeError("Tool artifact runtime context is not available")

        result = await workflow.ainvoke(
            ToolArtifactAnalyseInput(
                tool_call_id=tool_call_id,
                requirement=requirement,
                offset=offset,
            ),
            config=get_config(),
            context=runtime.context,
        )

        validated = ToolArtifactAnalyseResult.model_validate(result)
        return validated.model_dump(mode="json")

    trigger_tool_artifact_analyse.metadata = {
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    }

    return trigger_tool_artifact_analyse