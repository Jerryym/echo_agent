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
        同步执行工具（适用于支持 sync invoke 的工具）
        """
        try:
            handler = self._registry.get_handler(tool_call.name)
            result = handler.invoke(tool_call.args)
            return ToolResult(
                name=tool_call.name,
                result=result,
                success=True,
                tool_call_id=tool_call.tool_call_id,
            )
        except Exception as e:
            return ToolResult(
                name=tool_call.name,
                success=False,
                error=str(e),
                tool_call_id=tool_call.tool_call_id,
            )

    async def aexecute(self, tool_call: ToolCall) -> ToolResult:
        """
        异步执行工具（适用于 MCP 等仅支持 ainvoke 的工具）
        """
        try:
            handler = self._registry.get_handler(tool_call.name)
            result = await handler.ainvoke(tool_call.args)
            return ToolResult(
                name=tool_call.name,
                result=result,
                success=True,
                tool_call_id=tool_call.tool_call_id,
            )
        except Exception as e:
            return ToolResult(
                name=tool_call.name,
                success=False,
                error=str(e),
                tool_call_id=tool_call.tool_call_id,
            )
