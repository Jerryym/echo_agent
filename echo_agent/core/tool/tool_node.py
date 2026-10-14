from langgraph.runtime import Runtime

from ...common import format_value, get_logger
from ...utils import update_agent_tool
from ..graph import BaseContext, BaseState, Node
from ..model.conversation import ConversationContextItem, ConversationContextType
from ..model.message import Message, Role
from ..model.tool import ToolResultItem, ToolState
from .tool_executor import ToolExecutor
from .tool_result_store import ToolResultStore
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
    def __init__(self, name: str, tool_executor: ToolExecutor, message_field: str | None = None):
        super().__init__(name)
        self._tool_executor = tool_executor
        self._message_field = message_field
        self._tool_result_store = ToolResultStore()

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        同步运行（适用于支持 sync invoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_result_items: list[ToolResultItem] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            update_agent_tool(runtime.context, tool_call.name) # 记录调用的工具名
            result = self._tool_executor.execute(tool_call)
            result_item = self._tool_result_store.put(result)
            tool_result_items.append(result_item)
            # logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
        return self._build_result(tool_result_items, runtime.context)

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_result_items: list[ToolResultItem] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            update_agent_tool(runtime.context, tool_call.name) # 记录调用的工具名
            result = await self._tool_executor.aexecute(tool_call)
            result_item = self._tool_result_store.put(result)
            tool_result_items.append(result_item)
            # logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
        return self._build_result(tool_result_items, runtime.context)

    def _build_result(self, tool_result_items: list[ToolResultItem], context: BaseContext) -> dict:
        # 构建ToolMessage
        tool_messages = self._build_tool_messages(tool_result_items)
        # 构建ConversationContextItem
        context_items = self._build_context_items(tool_result_items)
        if context is not None and context_items:
            context.session_state.merge_context_items(context_items)

        result = {
            "tool_state": ToolState(tool_calls=[], tool_results=tool_result_items),
        }
        # 如果消息字段名称不为空, 则将工具调用消息添加到消息字段中
        if self._message_field is not None:
            result[self._message_field] = tool_messages

        logger.debug("appended %s ToolMessage(s) to messages", len(tool_messages))
        return result

    def _build_tool_messages(self, result_items: list[ToolResultItem]) -> list[Message]:
        """构建ToolMessage"""
        messages: list[Message] = []
        for item in result_items:
            if not item.success:
                content = item.error or "unknown error"
            elif item.storage == "memory":
                content = format_tool_content(item.result)
            else:
                content = ToolNode._format_external_result_content(item)

            messages.append(
                Message(
                    role=Role.TOOL,
                    content=content,
                    tool_call_id=item.tool_call_id,
                    status="success" if item.success else "error",
                )
            )
        return messages

    @staticmethod
    def _format_external_result_content(result_item: ToolResultItem) -> str:
        """构建外部存储的工具结果内容"""
        return (
            f"Tool '{result_item.name}' completed successfully. "
            "The complete result has been stored externally.\n"
            f"Tool call ID: {result_item.tool_call_id}\n"
            "The result is available for subsequent processing "
            "through the tool result management system."
        )

    @staticmethod
    def _build_context_items(result_items: list[ToolResultItem]) -> list[ConversationContextItem]:
        """构建工具结果的上下文项"""
        context_items: list[ConversationContextItem] = []
        for item in result_items:
            context_items.append(
                ConversationContextItem(
                    id=f"tool_result:{item.tool_call_id}",
                    type=ConversationContextType.TOOL_RESULT,
                    content=item.model_dump(mode="json"),
                )
            )

        return context_items
