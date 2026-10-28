from typing import Any, cast

from langchain_core.messages import ToolCall
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from ..core.model.tool import ToolCall as ModelToolCall


class ToolAdapter:
    """
    工具适配器
    """
    @staticmethod
    def to_langchain_tool_call(tool: ModelToolCall) -> ToolCall:
        """转换为 LangChain 工具调用"""
        return ToolCall(name=tool.name, args=tool.args, id=tool.tool_call_id)

    @staticmethod
    def to_langchain_tool_calls(tools: list[ModelToolCall]) -> list[ToolCall]:
        """转换为 LangChain 工具调用列表"""
        return [ToolAdapter.to_langchain_tool_call(tool) for tool in tools]

    @staticmethod
    def to_model_tool_call(tool: ToolCall) -> ModelToolCall:
        """转换为模型工具调用"""
        return ModelToolCall(
            name=tool["name"],
            args=tool.get("args", {}),
            tool_call_id=tool["id"],
        )

    @staticmethod
    def to_model_tool_calls(tools: list[ToolCall]) -> list[ModelToolCall]:
        """转换为模型工具调用列表"""
        return [ToolAdapter.to_model_tool_call(tool) for tool in tools]

    @staticmethod
    def to_openai_function_specs(tools: list[BaseTool | dict[str, Any]] | None) -> list[dict[str, Any]]:
        """
        转换为 OpenAI 函数规范

        e.g.:
        {
            "name": "get_weather",
            "description": "查询指定城市的天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市名称"
                    }
                },
                "required": ["location"]
            }
        }
        """
        specs: list[dict[str, Any]] = []
        for tool in tools or []:
            converted = convert_to_openai_tool(tool)
            if converted.get("type") != "function":
                raise ValueError("Only function tools are supported")
            function = converted.get("function")
            if not isinstance(function, dict):
                raise ValueError("Invalid function tool definition")
            specs.append(cast(dict[str, Any], function))
        return specs

    @staticmethod
    def to_openai_chat_tools(tools: list[BaseTool | dict[str, Any]] | None) -> list[dict[str, Any]]:
        """转换为 OpenAI Chat 工具"""
        return [{
            "type": "function", 
            "function": spec,
            }
            for spec in ToolAdapter.to_openai_function_specs(tools)
        ]

    @staticmethod
    def to_openai_response_tools(tools: list[BaseTool | dict[str, Any]] | None, builtin_tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """转换为 OpenAI Response 工具"""
        result: list[dict[str, Any]] = []
        for function in ToolAdapter.to_openai_function_specs(tools):
            parameters = function.get("parameters")
            item: dict[str, Any] = {
                "type": "function",
                "name": function["name"],
                "parameters": parameters if isinstance(parameters, dict) else {"type": "object", "properties": {}},
                "strict": False,
            }
            if "description" in function:
                item["description"] = function["description"]
            result.append(item)
        result.extend(dict(item) for item in (builtin_tools or []))
        return result
