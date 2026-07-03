from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..runtime import RuntimeConfig
from .node import Node, SubGraph
from .schema import BaseContext, BaseInput, BaseOutput, BaseState


START_NODE = START
END_NODE = END

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
    def __init__(self, state_schema: type[BaseState], context_schema: type[BaseContext] | None = None, input_schema: type[BaseInput] | None = None, output_schema: type[BaseOutput] | None = None):
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

    def compile(self, runtime_config: RuntimeConfig) -> CompiledStateGraph:
        builder = StateGraph(
            state_schema=self._state_schema,
            context_schema=self._context_schema,
            input_schema=self._input_schema,
            output_schema=self._output_schema,
        )

         # 注册节点
        for node in self._nodes.values():
            builder.add_node(node.name, node.run)

        # 注册边
        for from_node, to_node in self._edges:
            source = START if from_node == START_NODE else from_node
            target = END if to_node == END_NODE else to_node
            builder.add_edge(source, target)

        # 编译
        return builder.compile(checkpointer=runtime_config.checkpointer)