import json

from langgraph.runtime import Runtime

from ...common import format_debug
from ..graph import BaseContext, BaseState, Node
from ..model import Message, Role, ToolResult, ToolState
from .tool_executor import ToolExecutor


class ToolNode(Node):
    """
    Tool Node：工具执行节点

    Args:
        name: 节点名称
        tool_executor: 工具执行器
        message_field: 消息字段名称
    """
    def __init__(self, name: str, tool_executor: ToolExecutor, message_field: str | None = None):
        super().__init__(name, is_async=True)
        self._tool_executor = tool_executor
        self._message_field = message_field

    def run(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        同步运行（适用于支持 sync invoke 的工具）
        """
        print(f"[ReAct][tool] enter | calls={[tc.name for tc in state.tool_state.tool_calls]}")

        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            print(f"[ReAct][tool] executing {tool_call.name} args:")
            print(format_debug(tool_call.args))
            result = self._tool_executor.execute(tool_call)
            print(f"[ReAct][tool] result name={result.name} success={result.success}")
            print(format_debug(result.result))
            tool_results.append(result)

        return self._build_result(tool_results)

    async def arun(self, state: BaseState, runtime: Runtime[BaseContext]) -> dict:
        """
        异步运行（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        print(f"[ReAct][tool] enter | calls={[tc.name for tc in state.tool_state.tool_calls]}")

        tool_results: list[ToolResult] = []
        for tool_call in state.tool_state.tool_calls:
            print(f"[ReAct][tool] executing {tool_call.name} args:")
            print(format_debug(tool_call.args))
            result = await self._tool_executor.aexecute(tool_call)
            print(f"[ReAct][tool] result name={result.name} success={result.success}")
            print(format_debug(result.result))
            tool_results.append(result)

        return self._build_result(tool_results)

    def _build_result(self, tool_results: list[ToolResult]) -> dict:
        tool_messages = self._build_tool_messages(tool_results)
        print(f"[ReAct][tool] appended {len(tool_messages)} ToolMessage(s) to messages")
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
                if tool_result.success:# 执行成功, 将结果转换为字符串
                    content = json.dumps(tool_result.result, ensure_ascii=False, default=str)
                else:# 执行失败, 将错误信息转换为字符串
                    content = tool_result.error or "unknown error"
                # 构建 Message
                tool_messages.append(Message(
                    role=Role.TOOL,
                    content=content,
                    tool_call_id=tool_result.tool_call_id,
                ))
        return tool_messages
