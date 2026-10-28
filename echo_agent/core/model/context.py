from pydantic import BaseModel, Field

from .message import Message


class CompactedContext(BaseModel):
    """
    上下文压缩

    参数：
        goal: 当前任务目标或持续有效的用户目标
        facts: 已确认的重要事实、结果、数据及引用
        decisions: 已确认的决策与结论
        constraints: 仍然有效的要求、限制及偏好
        progress: 已完成的工作及当前执行进度
        pending: 尚未完成的事项、问题和阻塞
    """
    goal: str = Field(
        default="",
        description=(
            "The current objective or ongoing user goal. "
            "Preserve the latest valid intent."
        ),
    )
    facts: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed facts, important results, exact values, "
            "identifiers, paths, and references needed for "
            "continuation."
        ),
    )
    decisions: list[str] = Field(
        default_factory=list,
        description=(
            "Confirmed decisions and conclusions that remain "
            "relevant. Exclude proposals that were not accepted."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Applicable requirements, restrictions, and user "
            "preferences. Exclude superseded constraints."
        ),
    )
    progress: list[str] = Field(
        default_factory=list,
        description=(
            "Relevant execution progress, including completed, "
            "partial, failed, or unverified work. "
            "Do not imply success without evidence."
        ),
    )
    pending: list[str] = Field(
        default_factory=list,
        description=(
            "Remaining tasks, unresolved issues, and blockers "
            "necessary for continuing the work. "
            "Do not invent new tasks or plans."
        ),
    )


class ContextState(BaseModel):
    """
    工作上下文状态

    参数：
        messages: 消息列表
        context_window: 上下文窗口大小
        auto_compact_threshold: 自动压缩阈值
    """
    messages: list[Message] = Field(default_factory=list)
    context_window: int = Field(default=256_000, gt=0)
    auto_compact_threshold: int = Field(default=204_800, gt=0)
