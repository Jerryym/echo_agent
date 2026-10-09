from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .message import Message


class ConversationSummary(BaseModel):
    """
    对话摘要

    参数: 
        goal: 用户当前或持续性的主要目标 
        facts: 已确认且未来仍可能需要使用的事实
        decisions: 已经明确确定的结论或设计决策
        constraints: 后续交互仍需遵守的约束、要求或偏好
        completed: 已经完成且对后续任务有意义的事项
        pending: 尚未完成、仍需继续处理的事项
    """
    goal: str = Field(
        default="",
        description=(
            "The user's current or continuing primary goal. "
            "Describe what the user is trying to achieve. "
            "Preserve the goal while it remains relevant to the conversation. "
            "Do not describe execution status here."
        ),
    )
    facts: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed facts that may be needed in future turns. "
            "Include important entities, identifiers, mappings, relationships, "
            "attributes, values, execution results, and other reusable factual information. "
            "Only preserve facts that are supported by the conversation "
            "or confirmed tool results."
        ),
    )
    decisions: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed decisions, conclusions, or choices that should remain authoritative "
            "for future interactions unless explicitly changed later."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Requirements, restrictions, conventions, preferences, or technical constraints "
            "that remain applicable to future interactions."
        ),
    )
    completed: list[str] = Field(
        default_factory=list,
        description=(
            "Meaningful tasks, operations, investigations, or implementation steps "
            "that have already been completed. "
            "Record completion state here rather than duplicating returned values. "
            "Store reusable results in facts."
        ),
    )
    pending: list[str] = Field(
        default_factory=list,
        description=(
            "Tasks, questions, implementation steps, or decisions that remain unresolved "
            "and may require continuation in future turns."
        ),
    )

    def render(self) -> str:
        """将结构化摘要转换为模型可读文本"""
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) if items else "- (none)"
        
        return (
            "[Conversation Summary]\n"
            f"Goal: {self.goal or '(none)'}\n"
            f"Facts:\n{bullets(self.facts)}\n"
            f"Decisions:\n{bullets(self.decisions)}\n"
            f"Constraints:\n{bullets(self.constraints)}\n"
            f"Completed:\n{bullets(self.completed)}\n"
            f"Pending:\n{bullets(self.pending)}"
        )


class ConversationContextType(str, Enum):
    """会话上下文信息类型"""
    TOOL_RESULT = "tool_result"
    ARTIFACT = "artifact"
    FACT = "fact"
    ATTACHMENT = "attachment"


class ConversationContextItem(BaseModel):
    """
    会话上下文信息项

    参数:
        id: 对象ID
        type: 对象类型
        content: 对象内容
    """
    id: str
    type: ConversationContextType
    content: Any


class ConversationState(BaseModel):
    """
    对话状态

    参数:
        messages: 消息列表, 即历史记录
        summary: 对话摘要
        context_items: 会话上下文信息项列表
    """
    messages: list[Message] = Field(default_factory=list)
    summary: ConversationSummary | None = None
    context_items: list[ConversationContextItem] = Field(default_factory=list)


def merge_context_items(items: list[ConversationContextItem], new_items: list[ConversationContextItem]) -> list[ConversationContextItem]:
    """
    合并会话上下文信息

    合并原则: 相同 ID 更新，不同 ID 追加
    """
    merged = {item.id: item for item in items}

    for item in new_items:
        merged[item.id] = item

    return list(merged.values())
