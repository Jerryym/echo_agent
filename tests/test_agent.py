import os
from operator import add
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from echo_agent import Agent, BaseInput, BaseState, Graph, LLMClient, LLMConfig, Node
from echo_agent.core.agent import AgentConfig
from echo_agent.core.graph import START_NODE, END_NODE
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
    user_input: UserInput
    response: str = ""
    messages: Annotated[list[dict[str, Any]], add] = Field(default_factory=list)


# LLM invoke 节点
class LLMInvokeNode(Node):
    def __init__(self, name: str, llm_client: LLMClient, system_prompt: str):
        super().__init__(name)
        self._llm_client = llm_client
        self._system_prompt = system_prompt

    def run(self, state: State, context=None):
        result = self._llm_client.invoke(
            prompt=self._system_prompt,
            user_input=UserInput(text=state.user_input),
            history=state.messages,
        )
        return {
            "response": result.content,
            "messages": [
                {"role": "user", "content": state.user_input},
                {"role": "assistant", "content": result.content},
            ],
        }


def build_agent(name: str, config: LLMConfig, system_prompt: str) -> Agent:
    llm_client = LLMClient(config)
    graph = Graph(state_schema=State, input_schema=Input)
    llm_node = LLMInvokeNode("llm_node", llm_client, system_prompt)
    graph.add_node(llm_node)
    graph.add_edge(START_NODE, llm_node.name)
    graph.add_edge(llm_node.name, END_NODE)

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        system_prompt=system_prompt,
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


def build_user_input(text: str) -> UserInput:
    return UserInput(text={"user_input": text})


def extract_stream_text(event: dict) -> str:
    if not isinstance(event, dict) or event.get("method") != "messages":
        return ""

    payload = event["params"]["data"]
    if isinstance(payload, (list, tuple)):
        payload = payload[0]

    if isinstance(payload, dict) and payload.get("event") == "content-block-delta":
        return payload["delta"].get("text", "")

    if hasattr(payload, "content") and payload.content:
        content = payload.content
        if isinstance(content, str):
            return content

    return ""


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = agent.invoke(session_id, build_user_input(user_text))
        print("\nAssistant:")
        print(result.get("response", result))
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant: ", end="", flush=True)
        for event in agent.stream(session_id, build_user_input(user_text)):
            text = extract_stream_text(event)
            if text:
                print(text, end="", flush=True)
        print("\n\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    system_prompt = "You are a helpful assistant. Be concise."
    session_id = "test_session"

    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    agent = build_agent(
        "stream_agent" if mode == "1" else "invoke_agent",
        config,
        system_prompt,
    )

    if mode == "1":
        chat_stream(agent, session_id)
    else:
        chat_invoke(agent, session_id)
