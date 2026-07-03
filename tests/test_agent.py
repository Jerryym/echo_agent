from operator import add
import os
from pathlib import Path
from typing import Annotated

from pydantic import Field
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, BaseState, Graph, LLMConfig, Node
from echo_agent.core.agent import AgentConfig
from echo_agent.core.graph import BaseInput, END_NODE, START_NODE
from echo_agent.core.model import UserInput
from echo_agent.core.runtime import RuntimeConfig


def build_config():
    return LLMConfig(
        base_url=os.getenv("BASE_URL"),
        api_key=os.getenv("API_KEY"),
        model_name=os.getenv("MODEL_NAME"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),
        temperature=float(os.getenv("TEMPERATURE", 0.2)),
        max_tokens=int(os.getenv("MAX_TOKENS", 512)),
        timeout=int(os.getenv("TIMEOUT", 60)),
        max_retries=int(os.getenv("MAX_RETRIES", 2)),
    )


# 状态
class State(BaseState):
    foo: str = ""
    bar: Annotated[list[str], add] = Field(default_factory=list)

# 节点A
class NodeA(Node):
    def run(self, state: State):
        return {"foo": "a", "bar": ["a"]}

# 节点B
class NodeB(Node):
    def run(self, state: State):
        return {"foo": "b", "bar": ["b"]}

# 构建图
def build_graph() -> Graph:
    graph = Graph(state_schema=State)
    node_a = NodeA("node_a")
    node_b = NodeB("node_b")
    graph.add_node(node_a)
    graph.add_node(node_b)
    graph.add_edge(START_NODE, node_a.name)
    graph.add_edge(node_a.name, node_b.name)
    graph.add_edge(node_b.name, END_NODE)
    return graph

if __name__ == "__main__":
    load_dotenv()
    config = build_config()

    # 构建图
    graph = build_graph()

    # 构建 Agent
    agentconfig = AgentConfig(
        name="test_agent",
        description="test_agent",
        llm_config=config,
        graph=graph,
    )
    runtime_config = RuntimeConfig(
        checkpointer=InMemorySaver(),
    )
    agent = Agent(agentconfig, runtime_config, graph)

    print("====invoke====")
    result = agent.invoke(UserInput(text={"foo": "", "bar":[]}), "test_session_id_1")
    print(result)
    runconfig1={"configurable": {"thread_id": "test_session_id_1"}}
    runconfig_history_1 = list(agent.get_state_history(runconfig1))
    print(runconfig_history_1)

    print("====stream====")
    for chunk in agent.stream(UserInput(text={"foo": "", "bar":[]}), "test_session_id_2"):
        print(chunk)

    runconfig2={"configurable": {"thread_id": "test_session_id_2"}}
    runconfig_history_2 = list(agent.get_state_history(runconfig2))
    print(runconfig_history_2)