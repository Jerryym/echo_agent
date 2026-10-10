from pydantic import BaseModel, Field

from .conversation import ConversationContextItem, ConversationState, merge_context_items
from .token_usage import TokenUsage


class SessionState(BaseModel):
    """
    会话运行时状态

    参数:
        conversation: 已提交的运行时会话窗口
        context_items: 已提交的会话上下文信息项
        token_usage: 词元累计用量
    """
    conversation: ConversationState = Field(default_factory=ConversationState)
    context_items: list[ConversationContextItem] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def merge_context_items(self, new_items: list[ConversationContextItem]) -> None:
        """按 item ID 合并上下文：相同 ID 更新，不同 ID 追加"""
        self.context_items = merge_context_items(self.context_items, new_items)
