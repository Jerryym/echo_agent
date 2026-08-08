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
    user_goal: str = Field(description="用户持续有效的目标/约束，按优先级排列。勿编造。")
    context: list[str] = Field(default_factory=list, description="重要背景信息")
    decisions: list[str] = Field(default_factory=list, description="已经确定的决策")
    completed_tasks: list[str] = Field(default_factory=list, description="已经完成事项")
    pending_tasks: list[str] = Field(default_factory=list, description="待完成事项")
    constraints: list[str] = Field(default_factory=list, description="约束条件")
    important_facts: list[str] = Field(default_factory=list, description="需要长期保留的事实")


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