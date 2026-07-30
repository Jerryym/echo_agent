from pydantic import BaseModel, Field

from .message import Message


class ConversationState(BaseModel):
    """
    对话状态

    参数:
        messages: 消息列表, 即历史记录
    """
    messages: list[Message] = Field(default_factory=list)

    def append(self, *messages: Message) -> None:
        """
        追加消息
        """
        self.messages.extend(messages)


class AgentState(BaseModel):
    """
    智能体状态

    参数:
        session_id: 会话ID
        conversation: 对话状态
    """
    session_id: str
    conversation: ConversationState = Field(default_factory=ConversationState)
