from langgraph.graph import StateGraph

from agentconfig import AgentConfig
from llm import LLMConfig
from runtime.runtime_config import RuntimeConfig


class Agent:
    def __init__(self, agent_config: AgentConfig, runtime_config: RuntimeConfig):
        self._agent_config = agent_config
        self._runtime_config = runtime_config
        self._graph = self._build_graph(runtime_config.llm_config)

    def invoke(self):
        pass

    def stream(self):
        pass

    def _build_graph(self, llm_config: LLMConfig) -> StateGraph:
        graph = StateGraph()