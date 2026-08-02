from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import (
    Agent,
    AgentConfig,
    BaseContext,
    BaseState,
    LLMClient,
    LLMConfig,
    Node,
    RootGraph,
    UserInput,
)
from echo_agent.core.graph import START_NODE, END_NODE
from echo_agent.core.runtime import RuntimeConfig

from case.base import BaseCase, CaseResult
from case.common import extract_reply

REPO_ROOT = str(Path(__file__).resolve().parents[2])


class State(BaseState):
    response: str = ""


class LLMInvokeNode(Node):
    def __init__(self, name: str, llm_config: LLMConfig, system_prompt: str):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._system_prompt = system_prompt

    def run(self, state: State, context: BaseContext | None = None) -> dict:
        user_input = state.input
        if not isinstance(user_input, UserInput):
            user_input = UserInput(text=str(user_input))
        result = self._llm_client.invoke(
            prompt=self._system_prompt,
            user_input=user_input,
            history=state.messages,
        )
        content = result.content if isinstance(result.content, str) else str(result.content)
        return {
            "response": content,
            "messages": [
                user_input.to_human_message(),
                AIMessage(content=content),
            ],
        }

    async def arun(self, state: State, context: BaseContext | None = None, config=None) -> dict:
        raise NotImplementedError("LLMInvokeNode is sync-only")


def build_agent(name: str, config: LLMConfig, system_prompt: str) -> Agent:
    graph = RootGraph(state_schema=State)
    llm_node = LLMInvokeNode("llm_node", config, system_prompt)
    graph.add_node(llm_node)
    graph.add_edge(START_NODE, llm_node.name)
    graph.add_edge(llm_node.name, END_NODE)

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        system_prompt=system_prompt,
        mcp_allowed_directories=REPO_ROOT,
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


class AgentCase(BaseCase):
    """无策略 Agent：单 LLM 节点图。"""

    name = "agent"
    title = "Agent（无策略）"
    strategy = "None"

    def create_runtime(self, llm_config: LLMConfig | None) -> Agent:
        if llm_config is None:
            raise ValueError("Agent Case 需要 llm_config")
        return build_agent(
            "console_agent",
            llm_config,
            "You are a helpful assistant. Be concise.",
        )

    def on_message(self, runtime: Agent, session_id: str, text: str) -> CaseResult:
        result = runtime.invoke(session_id, UserInput(text=text))
        reply = extract_reply(result)
        state = runtime.get_state(session_id)
        return CaseResult(reply=reply, debug=f"state={getattr(state, 'values', state)}")
