"""
ReAct Agent + MCP 工具 手动验证脚本

与 test_react_agent.py 类似，工具来源改为 MCP Server（stdio / http）。
不含 HITL（MCP HITL 需后续按 LangChain Tool interceptors 设计）。

运行：
  uv run python tests/test_react_agent_mcp.py

http 默认连接：
  http://localhost:8000/mcp
"""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.mcp import MCPClient, MCPConnectionConfig
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolRegistry
from env_config import build_config

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

MCP_HTTP_URL = "http://localhost:8000/mcp"

MCP_TOOL_SETS: dict[str, tuple[str, MCPConnectionConfig]] = {
    "0": (
        "stdio",
        MCPConnectionConfig(
            name="everything",
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-everything"],
        ),
    ),
    "1": (
        "http",
        MCPConnectionConfig(
            name="remote",
            type="http",
            url=MCP_HTTP_URL,
        ),
    ),
}


class State(BaseState):
    pass


def select_mcp_tool_set() -> tuple[str, MCPConnectionConfig]:
    print("Available MCP tool sets:")
    for key, (name, config) in MCP_TOOL_SETS.items():
        detail = config.url if config.type == "http" else f"{config.command} {' '.join(config.args or [])}"
        print(f"  {key}: {name} ({config.type}) -> {detail}")
    choice = input("Choose MCP tool set (stdio=0 / http=1): ").strip()
    if choice not in MCP_TOOL_SETS:
        print(f"Unknown choice {choice!r}, fallback to stdio.")
        choice = "0"
    return MCP_TOOL_SETS[choice]


async def build_mcp_tool_registry(
    config: MCPConnectionConfig,
) -> tuple[MCPClient, ToolRegistry]:
    """注册 MCP 工具；返回 client 以保持连接/子进程存活。"""
    client = MCPClient([config])
    registry = ToolRegistry()
    definitions = await client.register_tools(registry)
    print(f"Registered {len(definitions)} MCP tools:")
    for definition in definitions:
        print(f"  - {definition.name} ({definition.type})")
    return client, registry


def build_react_agent(
    name: str,
    config: LLMConfig,
    tool_registry: ToolRegistry,
) -> Agent:
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
    """从 stream(v2) 事件中提取可打印的 token 文本。"""
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
    print("TEST: REACT AGENT MCP INVOKE")
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
    print("TEST: REACT AGENT MCP STREAM")
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


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "react_mcp_test_session"

    tool_set_name, mcp_config = select_mcp_tool_set()
    # 保持 client 引用，避免 stdio MCP Server 子进程被回收
    mcp_client, tool_registry = await build_mcp_tool_registry(mcp_config)

    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    agent_name = (
        f"react_mcp_stream_{tool_set_name}"
        if mode == "1"
        else f"react_mcp_invoke_{tool_set_name}"
    )
    agent = build_react_agent(agent_name, config, tool_registry)
    print(
        f"Using MCP tool set: {tool_set_name} "
        f"({len(tool_registry.list_definitions())} tools)"
    )

    if mode == "1":
        chat_stream(agent, session_id)
    else:
        chat_invoke(agent, session_id)

    # 显式保留引用，避免被优化掉
    _ = mcp_client


if __name__ == "__main__":
    asyncio.run(main())
