from typing import Sequence

from langchain_core.messages import BaseMessage
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ...model import Message, Role
from .tool_adapter import ToolAdapter


class MessageAdapter:
    """
    消息适配器
    """
    @staticmethod
    def to_langchain_message(message: Message) -> BaseMessage:
        """
        转换为 LangChain 消息
        """
        if message.role == Role.USER:
            return HumanMessage(content=message.content)
        if message.role == Role.SYSTEM:
            return SystemMessage(content=message.content)
        if message.role == Role.ASSISTANT:
            return AIMessage(content=message.content, tool_calls=ToolAdapter.to_langchain_tool_calls(message.tool_calls))
        if message.role == Role.TOOL:
            if message.tool_call_id:
                return ToolMessage(content=message.content, tool_call_id=message.tool_call_id)
            else:
                raise ValueError(f"Tool message '{message.content}' has no tool call ID.")
        raise NotImplementedError(f"Role '{message.role.value}' is not supported yet.")

    @staticmethod
    def to_langchain_messages(messages: Sequence[Message] | None = None) -> list[BaseMessage]:
        """
        转换为 LangChain 消息列表
        """
        if not messages:
            return []
        return [MessageAdapter.to_langchain_message(message) for message in messages]

    @staticmethod
    def to_message(message: BaseMessage) -> Message:
        """
        转换为消息
        """
        if isinstance(message, HumanMessage):
            return Message(role=Role.USER, content=message.content)
        if isinstance(message, SystemMessage):
            return Message(role=Role.SYSTEM, content=message.content)
        if isinstance(message, AIMessage):
            return Message(role=Role.ASSISTANT, content=message.content, tool_calls=ToolAdapter.to_model_tool_calls(message.tool_calls))
        if isinstance(message, ToolMessage):
            return Message(role=Role.TOOL, content=message.content, tool_call_id=message.tool_call_id)
        raise NotImplementedError(f"Message '{message}' is not supported yet.")

    @staticmethod
    def to_messages(messages: list[BaseMessage]) -> list[Message]:
        """
        转换为消息列表
        """
        return [MessageAdapter.to_message(message) for message in messages]
