from abc import ABC, abstractmethod

from ..graph import BaseContext, BaseInput, BaseOutput, BaseState, Node, SubGraph


class BaseStrategy(ABC):
    """
    策略基类
    """
    state_schema: type[BaseState]
    input_schema: type[BaseInput] | None = None
    output_schema: type[BaseOutput] | None = None
    context_schema: type[BaseContext] | None = None

    @abstractmethod
    def build(self) -> SubGraph:
        """
        构建策略子图
        """
        pass

    @abstractmethod
    def as_node(self) -> Node:
        """
        作为节点加入父图（Call a subgraph inside a node）
        """
        pass
