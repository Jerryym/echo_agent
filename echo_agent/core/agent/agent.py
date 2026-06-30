from typing import Iterator

from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import StateSnapshot

from ...runtime import RuntimeConfig
from ..graph import BaseInput, Graph
from ..model import UserInput
from .agent_config import AgentConfig


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、RuntimeConfig、Graph 等。

    Attributes:
        agent_config: Agent 配置
        runtime_config: Runtime 配置
        graph: Graph 图结构
        compiled_graph: 编译后的图
    """
    def __init__(self, agent_config: AgentConfig, runtime_config: RuntimeConfig, graph: Graph):
        self._agent_config = agent_config
        self._runtime_config = runtime_config
        self._graph = graph
        self._compiled_graph = self._graph.compile(runtime_config)

    def invoke(self, input: UserInput, session_id: str):
        """
        调用 Agent 执行

        Args:
            input: UserInput 用户输入
            session_id: 会话 ID
        """
        input = self._build_input(input)
        config = RunnableConfig(
            configurable={
                "thread_id": session_id,
            }
        )
        return self._compiled_graph.invoke(input, config)

    def stream(self, input: UserInput, session_id: str):
        """
        流式调用 Agent 执行

        Args:
            input: UserInput 用户输入
            session_id: 会话 ID
        """
        input = self._build_input(input)
        config = RunnableConfig(
            configurable={
                "thread_id": session_id,
            }
        )
        return self._compiled_graph.stream_events(input, config, version="v3")

    def get_state_history(self, session_id: str) -> Iterator[StateSnapshot]:
        return self._compiled_graph.get_state_history(RunnableConfig(configurable={"thread_id": session_id}))

    def _build_input(self, input: UserInput) -> BaseInput:
        """
        构建输入

        Args:
            input: UserInput 用户输入
        """
        return BaseInput(input=input)