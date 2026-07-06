from langchain_core.runnables.config import RunnableConfig

from ..runtime import RuntimeConfig
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

    def invoke(self, session_id: str, input: UserInput):
        """
        调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入
        """
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.invoke(input, runnable_config)

    def stream(self, session_id: str, input: UserInput, version: str = "v3"):
        """
        流式调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入
            version: 版本
        """
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.stream_events(input, runnable_config, version=version)
    
    def get_state(self, session_id: str, checkpoint_id: str | None = None):
        """
        [Debug] 获取当前状态

        Args:
            session_id: 会话 ID
            checkpoint_id: 检查点 ID
        """
        configurable = {
            "thread_id": session_id,
        }

        if checkpoint_id:
            configurable["checkpoint_id"] = checkpoint_id

        runnable_config = RunnableConfig(configurable=configurable)
        return self._compiled_graph.get_state(runnable_config)

    def get_state_history(self, session_id: str):
        """
        [Debug] 获取状态历史

        Args:
            session_id: 会话 ID
        """
        configurable = {
            "thread_id": session_id,
        }
        runnable_config = RunnableConfig(configurable=configurable)
        return self._compiled_graph.get_state_history(runnable_config)

    # def _build_input(self, input: UserInput) -> BaseInput:
    #     """
    #     构建输入

    #     Args:
    #         input: UserInput 用户输入
    #     """
    #     return BaseInput(input=input)

    def _build_runnable_config(self, session_id: str) -> RunnableConfig:
        """
        构建 RunnableConfig

        Args:
            session_id: 会话 ID
        """
        return RunnableConfig(
            configurable={
                "thread_id": session_id,
            }
        )