"""
ReAct Agent + MCP 工具 手动验证脚本

与 test_react_agent.py 类似，工具来源改为 MCP Server。
固定同时启用：
  - builtin：Fetch + Filesystem（目录由 mcp_allowed_directories 传入）
  - stdio：@modelcontextprotocol/server-everything
  - http：本地 streamable HTTP（默认 http://localhost:8000/mcp）

含 MCP 时走异步轨：ainvoke / astream。

装配对齐：
  AgentConfig.mcp_servers → Agent 内部构造 MCPClient → register_tools

运行：
  # 可选：终端 1 起本地 http MCP
  uv run python tests/mcp_server.py

  # 终端 2
  uv run python tests/test_react_agent_mcp.py
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
from echo_agent.core.mcp import MCPConnectionConfig
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolRegistry
from env_config import build_config

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

MCP_HTTP_URL = "http://localhost:8000/mcp"

MCP_SERVERS: list[MCPConnectionConfig] = [
    MCPConnectionConfig(
        name="everything",
        type="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-everything"],
    ),
    MCPConnectionConfig(
        name="remote",
        type="http",
        url=MCP_HTTP_URL,
    ),
]


class State(BaseState):
    pass


async def build_react_agent(
    name: str,
    llm_config: LLMConfig,
) -> tuple[Agent, ToolRegistry]:
    """
    AgentConfig → 内置 MCP + stdio/http → Agent.register_mcp_tools。

    因 Strategy 构建需要已注册工具，先用占位图创建 Agent，
    注册后再构建 ReAct 图并重新编译到同一 Agent。
    """
    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=llm_config,
        mcp_allowed_directories=str(Path(__file__).resolve().parents[1]),
        mcp_servers=MCP_SERVERS,
        enable_builtin_fetch=True,
        enable_builtin_filesystem=True,
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())

    placeholder = RootGraph(state_schema=State)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(agent_config, runtime_config, placeholder)
    assert agent.mcp_client is not None

    definitions = await agent.register_mcp_tools()
    print(f"Registered {len(definitions)} MCP tools:")
    for definition in definitions:
        print(f"  - {definition.name} ({definition.type})")

    react_subgraph = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=llm_config,
        tool_registry=agent.tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_node(react_subgraph)
    graph.add_edge(START_NODE, react_subgraph.name)
    graph.add_edge(react_subgraph.name, END_NODE)

    agent._graph = graph
    agent._compiled_graph = graph.compile(runtime_config)
    return agent, agent.tool_registry


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
    """从 astream(v2) 事件中提取可打印的 token 文本。"""
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


async def chat_ainvoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT MCP AINVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = await agent.ainvoke(session_id, UserInput(text=user_text))
        print("\nAssistant:")
        print(result.get("response", result))
        state = agent.get_state(session_id)
        print(f"[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


async def chat_astream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT MCP ASTREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant: ", end="", flush=True)
        async for chunk in await agent.astream(session_id, UserInput(text=user_text)):
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

    mode = input("Choose mode (ainvoke=0 / astream=1): ").strip()
    agent_name = "react_mcp_astream" if mode == "1" else "react_mcp_ainvoke"
    agent, tool_registry = await build_react_agent(agent_name, config)
    print(
        "Using MCP: builtin + stdio(everything) + http(remote); "
        f"{len(tool_registry.list_definitions())} tools; "
        f"agent.mcp_client is set={agent.mcp_client is not None}"
    )

    if mode == "1":
        await chat_astream(agent, session_id)
    else:
        await chat_ainvoke(agent, session_id)


if __name__ == "__main__":
    asyncio.run(main())
