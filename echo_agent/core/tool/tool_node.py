import json
from langchain_core.messages import ToolMessage

from ..graph import BaseContext, BaseState, Node
from ...common import format_debug
from .schema import ToolResult
from .tool_executor import ToolExecutor


class ToolNode(Node):
    """
    Tool Node：工具执行节点
    """
    def __init__(self, name: str, tool_executor: ToolExecutor):
        super().__init__(name)
        self._tool_executor = tool_executor

    def run(self, state: BaseState, context: BaseContext | None = None) -> dict:
        """
        Run the node
        """
        print(f"[ReAct][tool] enter | calls={[tc.name for tc in state.tool_calls]}")

        tool_results: list[ToolResult] = []
        # 执行工具
        for tool_call in state.tool_calls:
            print(f"[ReAct][tool] executing {tool_call.name} args:")
            print(format_debug(tool_call.args))
            result = self._tool_executor.execute(tool_call)
            print(f"[ReAct][tool] result name={result.name} success={result.success}")
            print(format_debug(result.result))
            tool_results.append(result)

        tool_messages: list[ToolMessage] = []
        if tool_results:
            for tool_result in tool_results:
                # 将结果转换为字符串
                content = json.dumps(tool_result.result, ensure_ascii=False, default=str)
                # 构建 ToolMessage
                tool_messages.append(ToolMessage(
                    content=content,
                    tool_call_id=tool_result.tool_call_id,
                ))

        print(f"[ReAct][tool] appended {len(tool_messages)} ToolMessage(s) to messages")
        for tm in tool_messages:
            print(f"[ReAct][tool] ToolMessage id={tm.tool_call_id}")
            print(format_debug(tm.content))

        # 更新状态
        return {
            "tool_results": tool_results,
            "tool_calls": [],
            "messages": tool_messages,
        }
