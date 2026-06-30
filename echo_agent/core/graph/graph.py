from node import Node, SubGraph
from schema import BaseContext, BaseInput, BaseOutput, BaseState


class Graph:
    """
    Graph 类：用于定义图结构，包括节点、边、子图等。

    参数：
        state_schema: 状态
        context_schema: 上下文
        input_schema: 输入
        output_schema: 输出
        nodes: 节点列表
        edges: 边列表
        subgraphs: 子图列表
    """
    def __init__(self, state_schema: BaseState, context_schema: BaseContext, input_schema: BaseInput, output_schema: BaseOutput):
        self._state_schema = state_schema
        self._context_schema = context_schema
        self._input_schema = input_schema
        self._output_schema = output_schema

        self._nodes: dict[str, Node] = {}
        self._edges: list[tuple[str, str]] = []
        self._subgraphs: list[SubGraph] = []

    def add_node(self, node: Node) -> None:
        self._nodes[node.name] = node

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges.append((from_node, to_node))

    def add_subgraph(self, subgraph: SubGraph) -> None:
        self._subgraphs.append(subgraph)