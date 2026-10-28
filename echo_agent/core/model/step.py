from uuid import uuid4

from pydantic import BaseModel, Field

from .token_usage import TokenUsage


class Step(BaseModel):
    """
    运行步

    参数:
        id: 步骤ID
        token_usage: 步骤使用的Token数量
        error: 步骤错误信息
    """
    id: str = Field(default_factory=lambda: uuid4().hex)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None
