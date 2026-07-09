from langchain_core.runnables.config import RunnableConfig

from ..graph import BaseInput, RootGraph
from ..model import UserInput
from ..runtime import RuntimeConfig
from .agent_config import AgentConfig


class Agent:
    """
    Agent 类：用于定义 Agent 的运行实体，包括 AgentConfig、RuntimeConfig、RootGraph 等。

    Attributes:
        agent_config: Agent 配置
        runtime_config: Runtime 配置
        graph: RootGraph 根图
        compiled_graph: 编译后的图
    """
    def __init__(self, agent_config: AgentConfig, runtime_config: RuntimeConfig, graph: RootGraph):
        self._agent_config = agent_config
        self._runtime_config = runtime_config
        self._graph = graph
        self._compiled_graph = self._graph.compile(runtime_config)

    def invoke(self, session_id: str, input: UserInput | type[BaseInput]):
        """
        调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.invoke(graph_input, runnable_config)

    def stream(self, session_id: str, input: UserInput | type[BaseInput], version: str = "v2"):
        """
        流式调用 Agent 执行

        Args:
            session_id: 会话 ID
            input: UserInput 用户输入 或 BaseInput 输入类型
            version: 版本
        """
        # 构建输入
        input_schema = self._graph.input_schema
        if input_schema is None: # 无输入类型时，直接使用UserInput
            graph_input = {"input": input}
        else: # 输入有类型时，使用input_schema进行类型检查，如果类型不匹配，则抛出TypeError
            if isinstance(input, input_schema):
                graph_input = input
            else:
                raise TypeError(f"输入类型错误，期望 {input_schema}，实际 {type(input)}")

        # 构建RunnableConfig
        runnable_config = self._build_runnable_config(session_id)
        return self._compiled_graph.stream(graph_input, runnable_config, stream_mode="messages", version=version)
    
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