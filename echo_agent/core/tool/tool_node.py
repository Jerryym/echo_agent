from langgraph.runtime import Runtime

from ...common import format_value, get_logger
from ..capability.skill import SkillManager
from ..graph import BaseContext, BaseState, Node
from ..model.message import Message, Role
from ..model.tool import ToolCall, ToolResult, ToolState
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
    """
    def __init__(self, name: str, tool_executor: ToolExecutor, message_field: str | None = None):
        super().__init__(name)
        self._tool_executor = tool_executor
        self._message_field = message_field

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        同步运行（适用于支持 sync invoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            result = self._tool_executor.execute(tool_call)
            logger.info(
                "result name=%s success=%s result=%s",
                result.name,
                result.success,
                format_value(result.result),
            )
            self._touch_skills_for_tool(runtime.context, tool_call)
            tool_results.append(result)
        return self._build_result(tool_results)

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        logger.info("enter | calls=%s", [tc.name for tc in state.tool_state.tool_calls])
        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            logger.info("executing %s args=%s", tool_call.name, format_value(tool_call.args))
            result = await self._tool_executor.aexecute(tool_call)
            logger.info(
                "result name=%s success=%s result=%s",
                result.name,
                result.success,
                format_value(result.result),
            )
            self._touch_skills_for_tool(runtime.context, tool_call)
            tool_results.append(result)
        return self._build_result(tool_results)

    def _touch_skills_for_tool(self, context: BaseContext, tool_call: ToolCall) -> None:
        """执行 allowed_tools 内工具时重置对应 skill 的 idle。"""
        definition = self._tool_executor.get_definition(tool_call.name)
        original_name = None
        if definition is not None:
            original_name = definition.meta_data.get("original_name")
        SkillManager.reset_idle_rounds_for_tool(context, tool_call.name, original_name)

    def _build_result(self, tool_results: list[ToolResult]) -> dict:
        tool_messages = self._build_tool_messages(tool_results)
        logger.debug("appended %s ToolMessage(s) to messages", len(tool_messages))
        result = {
            "tool_state": ToolState(tool_calls=[], tool_results=tool_results),
        }
        # 如果消息字段名称不为空, 则将工具调用消息添加到消息字段中
        if self._message_field is not None:
            result[self._message_field] = tool_messages
        return result

    def _build_tool_messages(self, tool_results: list[ToolResult]) -> list[Message]:
        tool_messages: list[Message] = []
        if tool_results:
            for tool_result in tool_results:
                if tool_result.success:
                    # 字符串结果直接作为 ToolMessage content，避免 json.dumps 多包一层引号
                    content = format_tool_content(tool_result.result)
                else:
                    content = tool_result.error or "unknown error"
                tool_messages.append(Message(
                    role=Role.TOOL,
                    content=content,
                    tool_call_id=tool_result.tool_call_id,
                ))
        return tool_messages
