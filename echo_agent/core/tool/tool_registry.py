from typing import Any

from .schema import ToolDefinition


class ToolRegistry:
    """
    Tool Registry：工具注册
    """
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Any] = {}

    def register(self, tool: ToolDefinition, handler: Any):
        self._tools[tool.name] = tool
        self._handlers[tool.name] = handler

    def unregister(self, name: str):
        self._tools.pop(name)
        self._handlers.pop(name)

    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in self._tools.values()
        ]
    
    def get(self, name: str) -> ToolDefinition:
        return self._tools[name]

    def get_handler(self, name: str) -> Any:
        return self._handlers[name]

    def list_definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())
