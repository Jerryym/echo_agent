from ...graph import Node, SubGraph
from .schema import ReActContext, ReActState


class ReActNode(Node):
    """
    React node
    """
    def __init__(self, name: str, subgraph: SubGraph):
        super().__init__(name)
        self._subgraph = subgraph

    def run(self, state: ReActState, context: ReActContext | None = None) -> dict:
        return self._subgraph.as_callable().invoke(state, context)
