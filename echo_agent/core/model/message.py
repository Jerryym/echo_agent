from enum import Enum

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel


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
    """
    role: Role
    content: str


def to_langchain_message(message: Message) -> BaseMessage:
    """转换为 LangChain Message"""
    if message.role == Role.USER:
        return HumanMessage(content=message.content)
    if message.role == Role.SYSTEM:
        return SystemMessage(content=message.content)
    if message.role == Role.ASSISTANT:
        return AIMessage(content=message.content)
    raise NotImplementedError(
        f"Role '{message.role.value}' is not supported yet."
    )

def to_langchain_messages(messages: list[Message]) -> list[BaseMessage]:
    """批量转换为 LangChain Message"""
    return [to_langchain_message(msg) for msg in messages]