from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .context import ContextState
from .conversation import ConversationState
from .token_usage import TokenUsage


class SessionItemType(str, Enum):
    """会话资源项的类型"""
    TOOL_RESULT = "tool_result"
    FACT = "fact"
    ATTACHMENT = "attachment"


class SessionItem(BaseModel):
    """
    会话资源项

    参数：
        id: 会话资源项的唯一标识符
        type: 会话资源项的类型
        content: 会话资源项的内容
    """
    id: str
    type: SessionItemType
    content: Any


class SessionState(BaseModel):
    """
    会话运行时状态

    参数:
        conversation: 已提交的运行时会话窗口
        context: 智能体运行时上下文
        items: 会话资源项列表
        token_usage: 词元累计用量
    """
    conversation: ConversationState = Field(default_factory=ConversationState)
    context: ContextState = Field(default_factory=ContextState)
    items: list[SessionItem] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def merge_session_items(self, new_items: list[SessionItem]) -> None:
        """按资源 ID 更新或追加会话资源项"""
        merged = {item.id: item for item in self.items}
        for item in new_items:
            merged[item.id] = item
        self.items = list(merged.values())
