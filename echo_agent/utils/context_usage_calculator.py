import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_function


class ContextUsageCalculator:
    """
    上下文用量计算器
    """
    @staticmethod
    def calculate(messages: list[BaseMessage], tools: list[dict[str, Any] | BaseTool] | None = None) -> int:
        message_tokens = count_tokens_approximately(messages)
        tool_tokens = ContextUsageCalculator._calculate_tool_tokens(tools)
        return message_tokens + tool_tokens

    @staticmethod
    def _calculate_tool_tokens(tools: list[dict[str, Any] | BaseTool]) -> int:
        if not tools:
            return 0

        serialized_tools: list[Any] = []
        for tool in tools:
            if isinstance(tool, BaseTool):
                serialized_tools.append(convert_to_openai_function(tool))
            else:
                serialized_tools.append(tool)

        content = json.dumps(
            serialized_tools
            ,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return count_tokens_approximately([HumanMessage(content=content)])
