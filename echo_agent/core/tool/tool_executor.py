from .schema import ToolCall, ToolResult
from .tool_registry import ToolRegistry


class ToolExecutor:
    """
    Tool Executor：工具执行器
    """
    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """
        Execute the tool
        """
        try:
            # 获取工具处理函数
            handler = self._registry.get_handler(
                tool_call.name
            )
            result = handler.invoke(tool_call.args)
            # 返回 ToolResult
            return ToolResult(
                name=tool_call.name,
                result=result,
                success=True,
                tool_call_id=tool_call.tool_call_id,
            )
        except Exception as e:
            return ToolResult(
                name=tool_call.name,
                result={
                    "error": str(e)
                },
                success=False,
                tool_call_id=tool_call.tool_call_id,
            )