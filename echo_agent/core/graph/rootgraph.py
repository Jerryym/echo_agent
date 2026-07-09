from langgraph.graph.state import CompiledStateGraph

from ..runtime import RuntimeConfig
from .graph import Graph


class RootGraph(Graph):
    """
    RootGraph：根图, RootGraph 是图的执行入口，负责将图结构编译为 LangGraph CompiledStateGraph，不负责图的执行。
    """
    def compile(self, runtime_config: RuntimeConfig) -> CompiledStateGraph:
        """
        编译图。
        """
        return self.build().compile(
            checkpointer=runtime_config.checkpointer,
            store=runtime_config.store,
        )
