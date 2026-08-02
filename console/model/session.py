from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class ChatMessageData:
    """会话内一条聊天记录。"""
    role: str  # "User" | "Assistant"
    content: str
    tokens: int | None = None


@dataclass
class SessionInfo:
    """
    会话信息
    """
    id: UUID = field(default_factory=uuid4)
    title: str = field(default="")
    messages: list[ChatMessageData] = field(default_factory=list)
