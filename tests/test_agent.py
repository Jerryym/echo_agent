from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import (
    Agent,
    BaseContext,
    BaseState,
    LLMClient,
    LLMConfig,
    Node,
    RootGraph,
)
from echo_agent.core.agent import AgentConfig
from echo_agent.core.graph import START_NODE, END_NODE, GraphCompileOptions
from echo_agent.core.model.message import Message, Role
from echo_agent.core.model.input import UserInput
from env_config import build_config

# 状态
class State(BaseState):
    response: str = ""


# LLM invoke 节点
class LLMInvokeNode(Node):
    def __init__(self, name: str, llm_config: LLMConfig, system_prompt: str):
        super().__init__(name)
        self._llm_client = LLMClient(llm_config)
        self._system_prompt = system_prompt

    def run(self, state: State, context: BaseContext | None = None) -> dict:
        user_input = state.input
        history = state.messages
        result = self._llm_client.invoke(
            prompt=self._system_prompt,
            user_input=user_input,
            history=history,
        )
        return {
            "response": result.text,
            "messages": [
                Message(role=Role.USER, content=user_input.text),
                Message(role=Role.ASSISTANT, content=result.text),
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
        allowed_directories=str(Path(__file__).resolve().parents[1]),
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())
    return Agent(agent_config, compile_options, graph)


def _message_chunk_text(message: AIMessageChunk) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


def extract_stream_text(chunk) -> str:
    """从 stream(v2) 事件中提取可打印的 token 文本。"""
    if isinstance(chunk, dict) and chunk.get("type") == "messages":
        message, _metadata = chunk["data"]
    elif isinstance(chunk, tuple) and len(chunk) == 2:
        message, _metadata = chunk
    else:
        return ""

    if not isinstance(message, AIMessageChunk):
        return ""

    return _message_chunk_text(message)


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = agent.invoke(session_id, UserInput(text=user_text))
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
        for chunk in agent.stream(session_id, UserInput(text=user_text)):
            text = extract_stream_text(chunk)
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
