from abc import ABC
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .node import Node
from .schema import BaseContext, BaseInput, BaseOutput, BaseState


START_NODE = START
END_NODE = END

class Graph(ABC):
    """
    Graph：图结构定义，负责描述一个 LangGraph，包括状态模型、节点和边，不负责图的编译与运行。

    参数：
        state_schema: 状态
        context_schema: 上下文
        input_schema: 输入
        output_schema: 输出
        nodes: 节点列表
        subgraphs: 子图列表
        edges: 边列表
        conditional_edges: 条件边列表
    """
    def __init__(self, state_schema: type[BaseState], context_schema: type[BaseContext] | None = None, input_schema: type[BaseInput] | None = None, output_schema: type[BaseOutput] | None = None):
        self._state_schema = state_schema
        self._context_schema = context_schema
        self._input_schema = input_schema
        self._output_schema = output_schema

        self._nodes: dict[str, Node] = {}
        self._subgraphs: dict[str, CompiledStateGraph] = {}
        self._edges: list[tuple[str, str]] = []
        self._conditional_edges: list[tuple[str, Callable[[Any], str], dict[str, str] | None]] = []

    @property
    def state_schema(self):
        return self._state_schema

    @property
    def context_schema(self):
        return self._context_schema

    @property
    def input_schema(self):
        return self._input_schema

    @property
    def output_schema(self):
        return self._output_schema

    def add_node(self, node: Node) -> None:
        self._nodes[node.name] = node

    def add_subgraph(self, name: str, subgraph: CompiledStateGraph) -> None:
        self._subgraphs[name] = subgraph

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges.append((from_node, to_node))

    def add_conditional_edges(self, from_node: str, condition: Callable[[Any], str], path_map: dict[str, str] | None = None) -> None:
        self._conditional_edges.append((from_node, condition, path_map))

    def build(self) -> StateGraph:
        """
        构建 LangGraph StateGraph。
        """
        kwargs: dict = {
            "state_schema": self._state_schema,
        }

        if self._context_schema is not None:
            kwargs["context_schema"] = self._context_schema
        if self._input_schema is not None:
            kwargs["input_schema"] = self._input_schema
        if self._output_schema is not None:
            kwargs["output_schema"] = self._output_schema
        builder = StateGraph(**kwargs)

        # 注册节点
        for node in self._nodes.values():
            builder.add_node(node.name, node.run)

        # 注册子图
        for name, subgraph in self._subgraphs.items():
            builder.add_node(name, subgraph)

        # 注册边
        for source, target in self._edges:
            builder.add_edge(
                START if source == START_NODE else source,
                END if target == END_NODE else target,
            )

        # 注册条件边
        for source, condition, path_map in self._conditional_edges:
            builder.add_conditional_edges(
                START if source == START_NODE else source,
                condition,
                path_map,
            )

        return builder
