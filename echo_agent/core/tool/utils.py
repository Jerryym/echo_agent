import json
from typing import Any

from langchain.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from .schema import ToolAnnotations, ToolDefinition, ToolType

from ...common import get_logger


logger = get_logger("tool")

def to_tool_list(tool_json_schema: list[dict[str, Any]]) -> list[ToolDefinition]:
    """
    将 OpenAI Tool JSON Schema 转换为工具列表
    """
    tool_list = []
    for tool in tool_json_schema:
        fn = tool["function"]
        tool_definition = ToolDefinition(
            name=fn["name"], 
            description=fn["description"], 
            parameters=fn["parameters"],
        )

        if tool.get("annotations"):
            tool_definition.annotations = ToolAnnotations(
                read_only_hint=tool.get("readOnlyHint"), # 工具是否只读、不修改数据
                destructive_hint=tool.get("destructiveHint"), # 是否可能造成删除或不可逆修改
                idempotent_hint=tool.get("idempotentHint"), # 重复调用是否具有相同效果
                open_world_hint=tool.get("openWorldHint"), # 是否访问或影响外部开放系统
            )
        tool_list.append(tool_definition)
    return tool_list


def to_openai_tool_json_schema(tool_list: list[ToolDefinition]) -> list[dict[str, Any]]:
    """
    将工具列表转换为 OpenAI Tool JSON Schema
    """
    results = []
    for tool in tool_list:
        tool_schema = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

        if tool.annotations is not None:
            tool_schema["annotations"] = {
                "readOnlyHint": tool.annotations.read_only_hint,
                "destructiveHint": tool.annotations.destructive_hint,
                "idempotentHint": tool.annotations.idempotent_hint,
                "openWorldHint": tool.annotations.open_world_hint,
            }
        results.append(tool_schema)
    return results


def to_tool_definition(tool: BaseTool, tool_type: ToolType = ToolType.FUNCTION) -> ToolDefinition:
    """
    将 LangChain Tool 转换为工具定义
    """
    logger.debug("to_tool_definition | tool=%s", tool)
    
    openai_tool = convert_to_openai_tool(tool)
    fn = openai_tool["function"]
    
    return ToolDefinition(
        type=tool_type,
        name=fn["name"],
        description=fn.get("description") or "",
        parameters=fn.get("parameters") or {},
        annotations=get_tool_annotations(tool),
    )


def get_tool_definition(tool_list: list[ToolDefinition], tool_name: str) -> ToolDefinition | None:
    """
    根据工具名称获取工具
    """
    for tool in tool_list:
        if tool.name == tool_name:
            return tool
    return None


def format_tool_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def get_tool_annotations(tool: BaseTool) -> ToolAnnotations:
    """
    获取 Tool annotations
    """
    metadata = tool.metadata or {}

    # BaseTool
    annotations = metadata.get("annotations")
    if isinstance(annotations, dict):
        return ToolAnnotations(
            read_only_hint=annotations.get("readOnlyHint"),
            destructive_hint=annotations.get("destructiveHint"),
            idempotent_hint=annotations.get("idempotentHint"),
            open_world_hint=annotations.get("openWorldHint"),
        )

    # MCP Tool
    return ToolAnnotations(
        read_only_hint=metadata.get("readOnlyHint"),
        destructive_hint=metadata.get("destructiveHint"),
        idempotent_hint=metadata.get("idempotentHint"),
        open_world_hint=metadata.get("openWorldHint"),
    )
