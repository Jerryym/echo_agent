from enum import Enum
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, model_validator

from .token_usage import TokenUsage
from .tool import ToolState


class StepStatus(str, Enum):
    """步骤状态"""
    RUNNING = "running"
    PENDING = "pending"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Step(BaseModel):
    """
    运行步

    参数:
        id: 步骤ID
        status: 步骤状态
        content_type: 步骤内容类型
        content: 步骤内容, 支持：文本、JSON、工具状态
        token_usage: 步骤使用的Token数量
        error: 步骤错误信息
    """
    id: str = Field(default_factory=lambda: uuid4().hex)
    status: StepStatus = Field(default=StepStatus.RUNNING)
    content_type: Literal["text", "json", "tool"] | None = None
    content: str | dict[str, JsonValue] | dict[str, ToolState] | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None

    @model_validator(mode="after")
    def restore_tool_content(self) -> Self:
        """按内容标识恢复工具状态，避免与普通 JSON 字典混淆。"""
        if self.content_type == "tool" and self.content is not None:
            self.content = TypeAdapter(dict[str, ToolState]).validate_python(self.content)
        return self
