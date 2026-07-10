from langgraph.graph.state import CompiledStateGraph

from ..graph import Node
from .emums import StrategyType
from .plan_execute import PlanExecuteStrategy
from .react import ReActStrategy


class StrategyFactory:
    """
    策略工厂
    """
    @staticmethod
    def create_as_subgraph(strategy_type: StrategyType, **kwargs) -> CompiledStateGraph:
        """
        创建策略子图，对应 LangGraph 子图接入方式：Add a subgraph as a node
        """
        if strategy_type == StrategyType.REACT:# ReAct 策略
            strategy =  ReActStrategy(**kwargs)
        elif strategy_type == StrategyType.PLAN_EXECUTE:# Plan Execute 策略
            strategy =  PlanExecuteStrategy(**kwargs)
        else:
            raise ValueError(f"Unsupported strategy type: {strategy_type}")
        # 返回策略子图
        return strategy.as_subgraph()

    @staticmethod
    def create_as_node(strategy_type: StrategyType, **kwargs) -> Node:
        """
        创建策略子图节点，对应 LangGraph 子图接入方式：Call a subgraph inside a node
        """
        if strategy_type == StrategyType.REACT:# ReAct 策略
            strategy =  ReActStrategy(**kwargs)
        elif strategy_type == StrategyType.PLAN_EXECUTE:# Plan Execute 策略
            strategy =  PlanExecuteStrategy(**kwargs)
        else:
            raise ValueError(f"Unsupported strategy type: {strategy_type}")
        # 返回策略节点
        return strategy.as_node()
