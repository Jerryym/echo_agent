from ..graph import BaseContext, BaseState, Node
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
            print(f"[ReAct][tool] executing {tool_call.name} args={tool_call.args}")
            result = self._tool_executor.execute(tool_call)
            print(
                f"[ReAct][tool] result name={result.name} success={result.success} "
                f"result={result.result!r}"
            )
            tool_results.append(result)

        # 更新状态
        return {
            "tool_results": tool_results,
        }