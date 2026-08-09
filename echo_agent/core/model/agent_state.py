from pydantic import BaseModel, Field

from .conversation import ConversationState
from .token_usage import TokenUsage


class AgentState(BaseModel):
    """
    智能体状态

    参数:
        session_id: 会话ID
        conversation: 对话状态
        token_usage: 词元累计用量
    """
    session_id: str
    conversation: ConversationState = Field(default_factory=ConversationState)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
