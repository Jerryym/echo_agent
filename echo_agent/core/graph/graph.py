from typing import Any, Callable

from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.utils.runnable import RunnableCallable

from .node import Node
from .graph_schema import GraphSchema
from .schema import BaseContext, BaseInput, BaseOutput, BaseState


START_NODE = START
END_NODE = END

class Graph:
    """
    Graph：图结构定义，负责描述一个 LangGraph，包括状态模型、节点和边，不负责图的编译与运行

    参数：
        graph_schema: 图
        nodes: 节点列表
        subgraphs: 子图列表
        edges: 边列表
        conditional_edges: 条件边列表
    """
    def __init__(self, graph_schema: GraphSchema):
        self._graph_schema = graph_schema
        self._nodes: dict[str, Node] = {}
        self._subgraphs: dict[str, CompiledStateGraph] = {}
        self._edges: list[tuple[str, str]] = []
        self._conditional_edges: list[tuple[str, Callable[[Any], str], dict[str, str] | None]] = []

# region 属性
    @property
    def state_schema(self) -> type[BaseState]:
        return self._graph_schema.state_schema

    @property
    def context_schema(self) -> type[BaseContext] | None:
        return self._graph_schema.context_schema

    @property
    def input_schema(self) -> type[BaseInput] | None:
        return self._graph_schema.input_schema

    @property
    def output_schema(self) -> type[BaseOutput] | None:
        return self._graph_schema.output_schema
# endregion

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
        构建 LangGraph StateGraph
        """
        kwargs: dict[str, Any] = {
            "state_schema": self._graph_schema.state_schema,
            "context_schema": self.context_schema or BaseContext, # 默认使用 BaseContext
        }

        if self.input_schema is not None:
            kwargs["input_schema"] = self.input_schema
        if self.output_schema is not None:
            kwargs["output_schema"] = self.output_schema
        builder = StateGraph(**kwargs)

        # 注册节点：同步 / 异步路径同时挂上，避免 is_async 标记与实现不一致时硬失败
        for node in self._nodes.values():
            builder.add_node(
                node.name,
                RunnableCallable(
                    func=node.run,
                    afunc=node.arun,
                    name=node.name,
                ),
            )

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
