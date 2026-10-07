import os
from pathlib import Path
import tempfile

from langgraph.runtime import Runtime

from ...common import format_value, get_logger
from ..graph import BaseContext, BaseState, Node
from ..model.message import Message, Role
from ..model.tool import ToolArtifact, ToolResult, ToolState
from .tool_artifact_manager import ToolArtifactManager
from .tool_executor import ToolExecutor
from .utils import format_tool_content

logger = get_logger("tool")


class ToolNode(Node):
    """
    Tool Node：工具执行节点

    Args:
        name: 节点名称
        tool_executor: 工具执行器
        message_field: 消息字段名称
        artifact_threshold: 工具结果写入 Message 的最大字节数
    """

    DEFAULT_ARTIFACT_THRESHOLD: int = 128 * 1024

    def __init__(self, name: str, tool_executor: ToolExecutor, message_field: str | None = None):
        super().__init__(name)
        self._tool_executor = tool_executor
        self._message_field = message_field
        self._artifact_threshold = self.DEFAULT_ARTIFACT_THRESHOLD
        self._artifact_manager = ToolArtifactManager()

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        同步运行（适用于支持 sync invoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            result = self._tool_executor.execute(tool_call)
            logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
            tool_results.append(result)
        return self._build_result(tool_results, runtime.context)

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            result = await self._tool_executor.aexecute(tool_call)
            logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
            tool_results.append(result)
        return self._build_result(tool_results, runtime.context)

    def _build_result(self, tool_results: list[ToolResult], context: BaseContext) -> dict:
        tool_messages = self._build_tool_messages(tool_results, context)
        logger.debug("appended %s ToolMessage(s) to messages", len(tool_messages))
        result = {
            "tool_state": ToolState(tool_calls=[], tool_results=tool_results),
        }
        # 如果消息字段名称不为空, 则将工具调用消息添加到消息字段中
        if self._message_field is not None:
            result[self._message_field] = tool_messages
        return result

    def _build_tool_messages(self, tool_results: list[ToolResult], context: BaseContext) -> list[Message]:
        tool_messages: list[Message] = []

        for tool_result in tool_results:
            if not tool_result.success:
                tool_messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result.error or "unknown error",
                        tool_call_id=tool_result.tool_call_id,
                    )
                )
                continue

            content = format_tool_content(tool_result.result)
            content_size = len(content.encode("utf-8"))
            if content_size <= self._artifact_threshold: # 工具结果小于阈值
                tool_messages.append(
                    Message(
                        role=Role.TOOL,
                        content=content,
                        tool_call_id=tool_result.tool_call_id,
                    )
                )
            else:
                artifact = self._artifact_manager.store(tool_result.tool_call_id, content)
                tool_messages.append(
                    Message(
                        role=Role.TOOL,
                        content=self._format_artifact_content(artifact),
                        artifact=artifact,
                        tool_call_id=tool_result.tool_call_id,
                    )
                )
                context.tool_artifacts[tool_result.tool_call_id] = artifact

        return tool_messages

    @staticmethod
    def _format_artifact_content(artifact: ToolArtifact) -> str:
        """
        Build the ToolMessage content for an externalized tool result.
        """
        return (
            "The tool completed successfully, but the result is too large "
            "to include directly in the conversation context. "
            "The complete result has been stored as an artifact.\n"
            f"Artifact tool_call_id: {artifact.tool_call_id}\n"
            f"Artifact size: {artifact.size} bytes.\n"
            "Use trigger_tool_artifact_analyse with the artifact "
            "tool_call_id to analyse the result."
        )
