from typing import Sequence

from langchain_core.messages import BaseMessage
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..core.model.message import Message, Role
from ..core.model.input import UserInput
from ..core.model.tool import ToolCall
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
    def to_human_message(user_input: UserInput) -> HumanMessage:
        """
        转换为HumanMessage
        """
        # 无附件
        if not user_input.attachments:
            return HumanMessage(content=user_input.text)
        # 有附件
        content = [
            {
                "type": "text",
                "text": user_input.text,
            }
        ]
        for attachment in user_input.attachments:
            if attachment.format == "base64":
                if attachment.type == "image":
                    content.append({
                        "type": attachment.type,
                        "base64": attachment.data,
                        "mime_type": "image/jpeg",
                    })
                elif attachment.type == "audio":
                    content.append({
                        "type": attachment.type,
                        "base64": attachment.data,
                        "mime_type": "audio/wav"
                    })
                elif attachment.type == "file":
                    content.append({
                        "type": attachment.type,
                        "base64": attachment.data,
                        "mime_type": "application/pdf",
                    })
            elif attachment.format == "url":
                content.append({
                    "type": attachment.type,
                    "url": attachment.data,
                })

        return HumanMessage(content=content)

    @staticmethod
    def to_tool_call_message(tool_calls: list[ToolCall]) -> Message:
        """
        转换为带工具调用的Assistant Message
        """
        return Message(
            role=Role.ASSISTANT,
            tool_calls=tool_calls,
        )

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
            return Message(
                role=Role.ASSISTANT, 
                content=message.content, 
                tool_calls=ToolAdapter.to_model_tool_calls(message.tool_calls)
                )
        if isinstance(message, ToolMessage):
            return Message(role=Role.TOOL, content=message.content, tool_call_id=message.tool_call_id)
        raise NotImplementedError(f"Message '{message}' is not supported yet.")

    @staticmethod
    def to_messages(messages: list[BaseMessage]) -> list[Message]:
        """
        转换为消息列表
        """
        return [MessageAdapter.to_message(message) for message in messages]
