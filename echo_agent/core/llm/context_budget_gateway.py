import json
from typing import Any

from langchain_core.tools import BaseTool

from ...utils.tool_adapter import ToolAdapter
from ..model.message import Message
from ..runtime.gateway import BaseGateWay


class ContextBudgetGateway(BaseGateWay):
    """上下文预算网关"""
    @staticmethod
    def calculate_total_tokens(messages: list[Message], tools: list[BaseTool | dict[str, Any]] | None = None) -> int:
        """计算总Token数"""
        tokens = ContextBudgetGateway.calculate_tokens(messages)
        if tools:
            specs = ToolAdapter.to_openai_chat_tools(tools)
            encoded = json.dumps(specs, ensure_ascii=False, default=str).encode("utf-8")
            tokens += (len(encoded) + 3) // 4
        return tokens

    @staticmethod
    def calculate_tokens(messages: list[Message]) -> int:
        """计算Token数"""
        payload = [message.model_dump(mode="json", exclude={"artifact"}) for message in messages]
        encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        return (len(encoded) + 3) // 4

    @staticmethod
    def is_over_budget(tokens: int, budget: int) -> bool:
        """是否超过预算"""
        return tokens > budget
