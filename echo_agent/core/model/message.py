from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .tool import ToolCall


class Role(Enum):
    """
    消息角色
    """
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """
    消息

    参数:
        role: 消息角色
        content: 消息内容
        tool_call_id: 工具调用ID
        tool_calls: 工具调用列表
    """
    role: Role
    content: str = Field(default="")
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_message(self):
        if self.role == Role.TOOL and not self.tool_call_id:
            raise ValueError("Tool message requires tool_call_id")
        if self.tool_calls and self.role != Role.ASSISTANT:
            raise ValueError("Only assistant messages may contain tool calls")
        if self.tool_call_id and self.role != Role.TOOL:
            raise ValueError("Only tool messages may contain tool_call_id")
        return self


def append_messages(messages: list[Message], new_messages: list[Message]) -> list[Message]:
    """
    追加消息
    """
    return messages + new_messages
