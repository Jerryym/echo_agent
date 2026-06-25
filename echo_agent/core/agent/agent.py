from langgraph.graph import StateGraph

from agentconfig import AgentConfig


class Agent:

    def __init__(self, agent_config: AgentConfig, graph: StateGraph):
        self._agent_config = agent_config
        self._graph = graph