from langgraph.graph.state import CompiledStateGraph

from .graph import Graph
from .schema import BaseContext, BaseInput, BaseOutput, BaseState


class SubGraph(Graph):
    """
    SubGraph：子图, SubGraph 是一种特殊的 Graph，可作为父图中的节点使用。支持 LangGraph 两种子图接入方式：
    1. Add a subgraph as a node
       builder.add_node("subgraph", subgraph.as_node())
    2. Call a subgraph inside a node
       result = subgraph.as_callable().invoke(...)
    """

    def __init__(self, name: str, state_schema: type[BaseState], context_schema: type[BaseContext] | None = None, input_schema: type[BaseInput] | None = None, output_schema: type[BaseOutput] | None = None):
        super().__init__(state_schema, context_schema, input_schema, output_schema)
        self._name = name

    @property
    def name(self) -> str:
        return self._name
    
    def compile(self) -> CompiledStateGraph:
        """
        编译子图。
        """
        return self.build().compile()

    def as_node(self) -> CompiledStateGraph:
        """
        作为节点加入父图（Add a subgraph as a node）。
        """
        return self.compile()

    def as_callable(self) -> CompiledStateGraph:
        """
        作为 Runnable 在节点内部调用（Call a subgraph inside a node）。
        """
        return self.compile()
