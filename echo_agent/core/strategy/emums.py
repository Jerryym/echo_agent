from enum import Enum


class StrategyType(Enum):
    """
    智能体策略
    """
    NONE = "none"
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"