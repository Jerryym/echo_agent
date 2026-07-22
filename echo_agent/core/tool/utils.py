from typing import Any

from langchain.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from .schema import ToolDefinition, ToolType


def to_tool_list(tool_json_schema: list[dict[str, Any]]) -> list[ToolDefinition]:
    """
    将 OpenAI Tool JSON Schema 转换为工具列表
    """
    tool_list = []
    for tool in tool_json_schema:
        fn = tool["function"]
        tool_list.append(ToolDefinition(name=fn["name"], description=fn["description"], parameters=fn["parameters"]))
    return tool_list


def to_tool_definition(tool: BaseTool, tool_type: ToolType = ToolType.FUNCTION) -> ToolDefinition:
    """
    将 LangChain Tool 转换为工具定义
    """
    openai_tool = convert_to_openai_tool(tool)
    fn = openai_tool["function"]
    return ToolDefinition(
        name=fn["name"],
        description=fn.get("description") or "",
        parameters=fn.get("parameters") or {},
        type=tool_type,
    )


def get_tool_definition(tool_list: list[ToolDefinition], tool_name: str) -> ToolDefinition | None:
    """
    根据工具名称获取工具
    """
    for tool in tool_list:
        if tool.name == tool_name:
            return tool
    return None
