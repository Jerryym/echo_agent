from langgraph.graph.state import CompiledStateGraph

from .compile_options import GraphCompileOptions
from .graph import Graph


class RootGraph(Graph):
    """
    RootGraph：根图, RootGraph 是图的执行入口，负责将图结构编译为 LangGraph CompiledStateGraph，不负责图的执行。
    """
    def compile(self, compile_options: GraphCompileOptions) -> CompiledStateGraph:
        """
        编译图。
        """
        return self.build().compile(
            checkpointer=compile_options.checkpointer,
            store=compile_options.store,
        )
