from abc import ABC, abstractmethod

from ..graph import BaseInput, BaseState, BaseOutput, BaseContext


class BaseStrategy(ABC):
    """
    策略基类
    """
    state_schema: type[BaseState]
    input_schema: type[BaseInput] | None = None
    output_schema: type[BaseOutput] | None = None
    context_schema: type[BaseContext] | None = None

    @abstractmethod
    def build(self):
        """
        构建策略
        """
        pass

    @abstractmethod
    def as_node(self):
        """
        以 Node 形式加入 Parent Graph
        """
        pass

    @abstractmethod
    def as_subgraph(self):
        """
        获取 Strategy Subgraph
        """
        pass