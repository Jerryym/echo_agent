from collections.abc import Sequence
import json
from typing import Any, cast

from langchain_core.messages import BaseMessage
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessage,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCall,
    ChatCompletionMessageToolCallParam,
)
from openai.types.responses import ResponseInputParam

from ..core.model.input import UserInput
from ..core.model.message import Message, Role
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
            if message.tool_call_id is None:
                raise ValueError("Tool message requires tool_call_id")
            return ToolMessage(
                content=message.content, 
                tool_call_id=message.tool_call_id,
                status=message.status or "success",
                artifact=message.artifact,
                )
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
        """转换为HumanMessage"""
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
                    "type": "text",
                    "text": f"[{attachment.type}] {attachment.data}",
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
            return Message(
                role=Role.TOOL,
                content=message.content,
                tool_call_id=message.tool_call_id,
                status=message.status,
                artifact=message.artifact,
            )
        raise NotImplementedError(f"Message type '{type(message).__name__}' is not supported.")

    @staticmethod
    def to_messages(messages: list[BaseMessage]) -> list[Message]:
        """转换为消息列表"""
        return [MessageAdapter.to_message(message) for message in messages]

    @staticmethod
    def to_openai_messages(messages: list[Message],) -> list[ChatCompletionMessageParam]:
        """将 Message 转换为 OpenAI Chat Completions Messages"""
        result: list[ChatCompletionMessageParam] = []

        for message in messages:
            content = message.content

            if message.role == Role.SYSTEM:# System
                result.append({
                    "role": "system",
                    "content": MessageAdapter._to_openai_text(content),
                })
            elif message.role == Role.USER: # User
                if isinstance(content, str):
                    result.append({
                        "role": "user",
                        "content": content,
                    })
                else:
                    content_part = MessageAdapter._to_openai_user_parts(content)
                    result.append({
                        "role": "user",
                        "content": content_part,
                    })
            elif message.role == Role.ASSISTANT: # Assistant
                tool_calls: list[ChatCompletionMessageToolCallParam] = []
                for tool_call in message.tool_calls:
                    tool_calls.append({
                        "id": tool_call.tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": json.dumps(
                                tool_call.args,
                                ensure_ascii=False,
                            ),
                        },
                    })

                assistant_content = MessageAdapter._to_openai_text(content)
                if tool_calls:
                    result.append({
                        "role": "assistant",
                        "content": assistant_content or None,
                        "tool_calls": tool_calls,
                    })
                else:
                    result.append({
                        "role": "assistant",
                        "content": assistant_content,
                    })
            elif message.role == Role.TOOL: # Tool
                if message.tool_call_id is None:
                    raise ValueError("Tool message requires tool_call_id")
                result.append({
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": MessageAdapter._to_openai_text(content),
                })
            else:
                raise ValueError(f"Unsupported role: {message.role}")

        return result

    @staticmethod
    def to_openai_response_input(messages: list[Message]) -> ResponseInputParam:
        result: ResponseInputParam = []
        for message in messages:
            if message.role == Role.TOOL:
                if not message.tool_call_id or not isinstance(message.content, str):
                    raise ValueError("Responses tool result requires a call_id and text content")
                result.append({"type": "function_call_output", "call_id": message.tool_call_id,
                            "output": message.content})
                continue
            if message.role == Role.ASSISTANT and message.tool_calls:
                if message.content:
                    if not isinstance(message.content, str):
                        raise ValueError("Assistant multimodal content is not supported by this converter")
                    result.append({"role": "assistant", "content": message.content})
                for call in message.tool_calls:
                    result.append({"type": "function_call", "call_id": call.tool_call_id,
                                "name": call.name, "arguments": json.dumps(call.args, ensure_ascii=False)})
                continue
            if not isinstance(message.content, str):
                raise ValueError(f"Responses multimodal content unsupported for {message.role.value}")
            result.append(cast(Any, {"role": message.role.value, "content": message.content}))
        return result

    @staticmethod
    def from_openai_message(message: ChatCompletionMessage) -> Message:
        """将 OpenAI ChatCompletionMessage 转换为 AgentNest Message"""
        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for tool_call in message.tool_calls:
                if not isinstance(tool_call, ChatCompletionMessageToolCall):
                    raise ValueError(
                        f"Unsupported tool call type: {tool_call.type}"
                    )

                try:
                    args: Any = json.loads(
                        tool_call.function.arguments
                    )
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid tool arguments: {tool_call.function.name}"
                    ) from exc

                if not isinstance(args, dict):
                    raise ValueError(
                        "Tool arguments must be a JSON object"
                    )

                tool_calls.append(
                    ToolCall(
                        name=tool_call.function.name,
                        args=args,
                        tool_call_id=tool_call.id,
                    )
                )

        return Message(
            role=Role.ASSISTANT,
            content=message.content or "",
            tool_calls=tool_calls,
        )

    @staticmethod
    def _to_openai_text(content: str | list[str | dict[str, Any]]) -> str:
        """提取纯文本内容"""
        if isinstance(content, str):
            return content

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue

            if item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue

            raise ValueError("Non-text content cannot be converted to plain text")

        return "\n".join(parts)

    @staticmethod
    def _to_openai_user_parts(content: list[str | dict[str, Any]]) -> list[ChatCompletionContentPartParam]:
        """将用户多模态内容转换为 OpenAI content parts"""
        parts: list[ChatCompletionContentPartParam] = []
        for item in content:
            if isinstance(item, str):
                part: ChatCompletionContentPartTextParam = {
                    "type": "text",
                    "text": item,
                }
                parts.append(part)
                continue

            item_type = item.get("type")
            if item_type == "text": # 文本
                text = item.get("text")
                if not isinstance(text, str):
                    raise ValueError("Invalid text content")
                parts.append({
                    "type": "text",
                    "text": text,
                })
            elif item_type == "image_url": # 图片链接
                image_url = item.get("image_url")
                if not isinstance(image_url, dict):
                    raise ValueError("Invalid image_url content")
                # 获取图片URL
                url = image_url.get("url")
                if not isinstance(url, str):
                    raise ValueError("Invalid image URL")
                image_part: ChatCompletionContentPartImageParam = {
                    "type": "image_url",
                    "image_url": {"url": url},
                }
                detail = image_url.get("detail")
                if detail in ("auto", "low", "high"):
                    image_part["image_url"]["detail"] = detail

                parts.append(image_part)
            elif item_type == "image": # Base64编码的图片
                base64_data = item.get("base64")
                mime_type = item.get("mime_type")

                if not isinstance(base64_data, str):
                    raise ValueError("Invalid image base64")
                if not isinstance(mime_type, str):
                    raise ValueError("Invalid image MIME type")
                if not mime_type.startswith("image/"):
                    raise ValueError("Invalid image MIME type")
                parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:{mime_type};base64,"
                            f"{base64_data}"
                        ),
                    },
                })
            else:
                raise ValueError(f"Unsupported user content type: {item_type}")

        return parts
