from .emums import StrategyType
from .plan_execute import PlanExecuteStrategy
from .react import ReActStrategy
from .strategy import BaseStrategy


class StrategyFactory:
    """
    策略工厂
    """
    @staticmethod
    def create(strategy_type: StrategyType) -> BaseStrategy:
        """
        创建策略
        """
        if strategy_type == StrategyType.REACT:# ReAct 策略
            return ReActStrategy()
        elif strategy_type == StrategyType.PLAN_EXECUTE:# Plan Execute 策略
            return PlanExecuteStrategy()
        else:
            raise ValueError(f"Unsupported strategy type: {strategy_type}")