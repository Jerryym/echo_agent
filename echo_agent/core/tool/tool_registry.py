from typing import Any

from .schema import ToolDefinition
from .utils import to_openai_tool_json_schema


# 默认工具
DEFAULT_TOOLS = frozenset({
    "load_skill", # 加载SKILL
    "read_skill_resource", # 读取SKILL资源
})

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
        return to_openai_tool_json_schema(self.list_definitions())
    
    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_handler(self, name: str) -> Any | None:
        return self._handlers.get(name)

    def list_definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def default_tools(self) -> list[ToolDefinition]:
        return [
            tool for tool in self._tools.values() if tool.name in DEFAULT_TOOLS
        ]
