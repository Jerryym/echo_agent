from pathlib import Path
import warnings

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.graph import START_NODE, END_NODE
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolRegistry
from env_config import build_config
from tools.business_tools import BUSINESS_TOOLS

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

class State(BaseState):
    pass


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_obj in BUSINESS_TOOLS:
        tool = convert_to_openai_tool(tool_obj)
        fn = tool["function"]
        registry.register(
            ToolDefinition(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"],
            ),
            tool_obj,
        )
    return registry


def build_react_agent(name: str, config: LLMConfig) -> Agent:
    tool_registry = build_tool_registry()

    # 创建 ReAct 策略子图
    react_subgraph = StrategyFactory.create_as_subgraph(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=tool_registry,
    )

    graph = RootGraph(state_schema=State)
    graph.add_subgraph("ReAct", react_subgraph)
    graph.add_edge(START_NODE, "ReAct")
    graph.add_edge("ReAct", END_NODE)

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


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


def extract_stream_text(chunk, *, node: str | None = "final") -> str:
    """从 stream(v2) 事件中提取可打印的 token 文本。

    Args:
        chunk: Agent.stream() 产出的事件
        node: 只提取指定 LangGraph 节点的 token；None 表示不过滤
    """
    metadata = None

    if isinstance(chunk, dict) and chunk.get("type") == "messages":
        message, metadata = chunk["data"]
    elif isinstance(chunk, tuple) and len(chunk) == 2:
        message, metadata = chunk
    else:
        return ""

    if not isinstance(message, AIMessageChunk):
        return ""

    if node is not None and metadata and metadata.get("langgraph_node") != node:
        return ""

    return _message_chunk_text(message)


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = agent.invoke(session_id, UserInput(text=user_text))
        print("\nAssistant:")
        print(result.get("response", result))
        state = agent.get_state(session_id)
        print(f"[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant: ", end="", flush=True)
        for chunk in agent.stream(session_id, UserInput(text=user_text)):
            text = extract_stream_text(chunk, node="final")
            if text:
                print(text, end="", flush=True)
        state = agent.get_state(session_id)
        print(f"\n[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "react_test_session"

    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    agent = build_react_agent(
        "react_stream_agent" if mode == "1" else "react_invoke_agent",
        config,
    )

    if mode == "1":
        chat_stream(agent, session_id)
    else:
        chat_invoke(agent, session_id)
