from abc import ABC, abstractmethod
from functools import cached_property

from langgraph.graph.state import CompiledStateGraph

from ..graph import BaseContext, BaseInput, BaseOutput, BaseState, Node, SubGraph


class BaseStrategy(ABC):
    """
    策略基类
    """
    state_schema: type[BaseState]
    input_schema: type[BaseInput] | None = None
    output_schema: type[BaseOutput] | None = None
    context_schema: type[BaseContext] | None = None

    def __init__(
        self,
        state_schema: type[BaseState],
        input_schema: type[BaseInput] | None = None,
        output_schema: type[BaseOutput] | None = None,
        context_schema: type[BaseContext] | None = None,
    ):
        self.state_schema = state_schema
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.context_schema = context_schema

    @cached_property
    def compiled_graph(self):
        """
        编译后的策略子图
        """
        return self.build().as_callable()

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

    def as_subgraph(self) -> CompiledStateGraph:
        """
        作为子图加入父图（Add a subgraph as a node）
        """
        return self.compiled_graph

    @abstractmethod
    def to_strategy_input(self, state: BaseState, context: BaseContext | None = None) -> BaseInput:
        """
        将 Parent State 映射为 Strategy Input
        """
        pass

    def to_strategy_context(self, context: BaseContext | None = None) -> BaseContext | None:
        """
        将 Parent Context 映射为 Strategy Context
        """
        pass

    @abstractmethod
    def to_parent_state(self, output: BaseOutput) -> dict:
        """
        将 Strategy Output 映射为 Parent State 更新内容
        """
        pass

    def invoke(self, state: BaseState, context: BaseContext | None = None) -> dict:
        """
        调用策略
        """
        input = self.to_strategy_input(state, context)
        strategy_context  = self.to_strategy_context(context)
        output = self.compiled_graph.invoke(input, context=strategy_context)
        # 构建成输出模型
        if self.output_schema is not None and isinstance(output, dict):
            output = self.output_schema(**output)
        return self.to_parent_state(output)
