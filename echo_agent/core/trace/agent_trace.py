from datetime import datetime, timezone
import uuid

from pydantic import BaseModel, Field

from ..model.message import Message
from ..model.tool import ToolCall, ToolResult
from .token_usage import TokenUsage


class AgentTrace(BaseModel):
    """
    智能体执行跟踪

    Args:
        session_id: 会话ID
        trace_id: 跟踪ID
        created_at: 创建时间
        message: 消息列表
        tool_calls: 工具调用列表
        tool_results: 工具结果列表
        token_usage: 词元使用情况
    """
    session_id: str
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
