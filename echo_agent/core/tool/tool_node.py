from ..graph import Node, BaseState, BaseContext


class ToolNode(Node):
    """
    Tool Node：工具执行节点
    """
    def __init__(self, name: str):
        super().__init__(name)

    def run(self, state: BaseState, context: BaseContext | None = None) -> dict:
        """
        Run the node
        """
        pass