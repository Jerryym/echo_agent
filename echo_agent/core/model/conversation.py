from pydantic import BaseModel, Field

from .message import Message


class ConversationSummary(BaseModel):
    """
    对话摘要

    参数:
        user_goal: 用户当前主要目标
        context: 重要背景信息
        decisions: 已经确定的设计决策
        completed_tasks: 已经完成事项
        pending_tasks: 待完成事项
        constraints: 约束条件
        important_facts: 需要长期保留的事实
    """
    user_goal: str = Field(
        description=(
            "The user's current or continuing primary goal. "
            "Describe what the user wants, not whether the task succeeded or failed. "
            "If the original goal has been completed but remains the main conversation topic, "
            "preserve the goal itself. Do not invent information."
        )
    )
    context: list[str] = Field(
        default_factory=list,
        description=(
            "Important background information required to understand future turns, "
            "including the current subject, entity relationships, and reference context."
        ),
    )
    decisions: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed decisions or conclusions that may affect future interactions."
        ),
    )
    completed_tasks: list[str] = Field(
        default_factory=list,
        description=(
            "Tasks or operations that have already been completed. "
            "Record completed queries, tool executions, or actions when relevant. "
            "Store important returned values in important_facts."
        ),
    )
    pending_tasks: list[str] = Field(
        default_factory=list,
        description=(
            "Tasks, questions, or actions that remain unresolved or still require follow-up."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit requirements, restrictions, preferences, or limitations "
            "that must remain in effect."
        ),
    )
    important_facts: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed facts that may be required in future interactions. "
            "Preserve important query results, tool outputs, entity identifiers, "
            "name-to-ID mappings, relationships, attributes, and key values. "
            "For example: 'Zhang Wei has user_id u001'. "
            "Do not store these facts only in user_goal or completed_tasks."
        ),
    )

    def render(self) -> str:
        """将结构化摘要转换为模型可读文本"""
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) if items else "- (none)"
        
        return (
            "[Conversation Summary]\n"
            f"Goal: {self.user_goal}\n"
            f"Context:\n{bullets(self.context)}\n"
            f"Decisions:\n{bullets(self.decisions)}\n"
            f"Completed:\n{bullets(self.completed_tasks)}\n"
            f"Pending:\n{bullets(self.pending_tasks)}\n"
            f"Constraints:\n{bullets(self.constraints)}\n"
            f"Facts:\n{bullets(self.important_facts)}"
        )


class ConversationState(BaseModel):
    """
    对话状态

    参数:
        messages: 消息列表, 即历史记录
        summary: 对话摘要

    追加消息请使用 ``append_messages`` 写回 ``messages``，与 trajectory
    等 LangGraph reducer 语义保持一致。
    """
    messages: list[Message] = Field(default_factory=list)
    summary: ConversationSummary | None = None
