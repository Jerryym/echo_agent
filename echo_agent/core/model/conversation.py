from pydantic import BaseModel, Field

from .message import Message


class ConversationState(BaseModel):
    """
    对话状态

    参数:
        messages: 消息列表, 即历史记录
    """
    messages: list[Message] = Field(default_factory=list)
