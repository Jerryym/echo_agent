from pydantic import BaseModel, Field


class StrategyTask(BaseModel):
    """
    策略任务：用于描述一次执行目标

    Args:
        name: 任务名称
        description: 任务描述
        goal: 任务目标
    """
    name: str = Field(default="", description="任务名称")
    description: str = Field(default="", description="任务描述")
    goal: str = Field(default="", description="任务目标")
