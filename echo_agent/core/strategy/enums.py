from enum import Enum


class StrategyType(Enum):
    """
    智能体策略
    """
    REACT = "react"
    PLAN_EXECUTE = "plan_execute"