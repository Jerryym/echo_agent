from langgraph.graph import CompiledGraph

from node import Node, SubGraph
from schema import BaseContext, BaseInput, BaseOutput, BaseState


class Graph:
    """
    Graph 类
    """
    def __init__(self, state_schema: BaseState, context_schema: BaseContext, input_schema: BaseInput, output_schema: BaseOutput):
        self._state_schema = state_schema
        self._context_schema = context_schema
        self._input_schema = input_schema
        self._output_schema = output_schema

    def add_node(self, node: Node) -> None:
        pass

    def add_edge(self, from_node: Node, to_node: Node) -> None:
        pass

    def add_subgraph(self, subgraph: SubGraph) -> None:
        pass

    def compile(self) -> CompiledGraph:
        pass