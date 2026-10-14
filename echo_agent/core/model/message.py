from enum import Enum
from typing import Any, Literal, Self

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
        status: 工具消息执行状态
        artifact: 工具消息附加数据
    """
    role: Role
    content: str | list[str | dict[str, Any]] = Field(default="")

    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    status: Literal["success", "error"] | None = None
    artifact: Any | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_message(self) -> Self:
        if self.role == Role.TOOL:
            if not self.tool_call_id:
                raise ValueError("Tool message requires tool_call_id")
        else:
            if self.tool_call_id is not None:
                raise ValueError("Only tool messages may contain tool_call_id")
            if self.status is not None:
                raise ValueError("Only tool messages may contain status")
            if self.artifact is not None:
                raise ValueError("Only tool messages may contain artifact")

        if self.tool_calls and self.role != Role.ASSISTANT:
            raise ValueError("Only assistant messages may contain tool calls")

        return self


def append_messages(messages: list[Message], new_messages: list[Message]) -> list[Message]:
    """
    追加消息
    """
    return messages + new_messages
