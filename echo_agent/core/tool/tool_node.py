from langgraph.runtime import Runtime

from ...common import format_value, get_logger
from ...utils import update_agent_tool
from ..graph import BaseContext, BaseState, Node
from ..model.session import SessionItemType, SessionItem
from ..model.message import Message, Role, append_messages
from ..model.tool import ToolResultItem, ToolState
from ..model.step import StepStatus
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
        message_field: 可选的执行轨迹字段，工具消息始终写入工作上下文
        tool_result_store: 工具结果存储器
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
        tool_calls = [item.tool_call for item in state.tool_states.values()]
        logger.info("enter | calls=%s", [tool_call.name for tool_call in tool_calls])

        tool_result_items: list[ToolResultItem] = []
        for tool_call in tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            update_agent_tool(runtime.context, tool_call.name) # 记录调用的工具名
            result = self._tool_executor.execute(tool_call)
            result_item = self._tool_result_store.put(result)
            tool_result_items.append(result_item)
            # logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
        return self._build_result(tool_result_items, runtime.context, state)

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        tool_calls = [item.tool_call for item in state.tool_states.values()]
        logger.info("enter | calls=%s", [tool_call.name for tool_call in tool_calls])

        tool_result_items: list[ToolResultItem] = []
        for tool_call in tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            update_agent_tool(runtime.context, tool_call.name) # 记录调用的工具名
            result = await self._tool_executor.aexecute(tool_call)
            result_item = self._tool_result_store.put(result)
            tool_result_items.append(result_item)
            # logger.info("result name=%s success=%s result=%s", result.name, result.success, format_value(result.result))
        return self._build_result(tool_result_items, runtime.context, state)

    def _build_result(self, tool_result_items: list[ToolResultItem], context: BaseContext, state: BaseState) -> dict:
        # 构建ToolMessage
        tool_messages = self._build_tool_messages(tool_result_items)
        # 构建SessionItem
        session_items = self._build_session_items(tool_result_items)
        if context is not None and session_items:
            context.session_state.merge_session_items(session_items)
        # 构建工具状态
        tool_states = self._build_tool_states(state, tool_result_items)

        # 判断工具执行是否都成功
        is_all_success = all(item.success for item in tool_result_items)
        if is_all_success:
            step_status = StepStatus.COMPLETED
        else:
            step_status = StepStatus.FAILED

        # 更新运行步状态
        step = state.current_step
        if step is not None:
            step.status = step_status
            step.content_type = "tool"
            step.content = tool_states

            snapshot = step.model_copy(deep=True)
            if any(item.id == step.id for item in state.steps):
                state.steps = [snapshot if item.id == step.id else item for item in state.steps]
            else:
                state.steps = [*state.steps, snapshot]
            if step.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.CANCELLED):
                state.current_step = None

        work_context = state.context.model_copy(deep=True)
        work_context.messages = append_messages(work_context.messages, tool_messages)
        result: dict[str, object] = {
            "context": work_context,
            "tool_states": tool_states,
            "steps": state.steps,
            "current_step": state.current_step,
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
                content = self._format_external_result_content(item)

            messages.append(
                Message(
                    role=Role.TOOL,
                    content=content,
                    tool_call_id=item.tool_call_id,
                    status="success" if item.success else "error",
                )
            )
        return messages

    def _build_session_items(self, result_items: list[ToolResultItem]) -> list[SessionItem]:
        """构建工具结果的上下文项"""
        session_items: list[SessionItem] = []
        for item in result_items:
            session_items.append(
                SessionItem(
                    id=f"tool_result:{item.tool_call_id}",
                    type=SessionItemType.TOOL_RESULT,
                    content=item.model_dump(mode="json"),
                )
            )
        return session_items

    def _build_tool_states(self, state: BaseState, result_items: list[ToolResultItem]) -> dict[str, ToolState]:
        """构建工具状态"""
        tool_states = {
            item.tool_call_id: ToolState(
                tool_call=state.tool_states[item.tool_call_id].tool_call,
                tool_result=item,
            )
            for item in result_items
        }
        return tool_states

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
