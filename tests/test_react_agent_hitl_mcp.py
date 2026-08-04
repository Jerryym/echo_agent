"""
ReAct Agent + MCP 工具 + HITL 手动验证脚本

组合 test_react_agent_mcp（MCP 异步轨）与 test_react_agent_hitl（interrupt / resume）。
HITL 由 ReAct ActionNode 触发（缺参 → INPUT，required_approval → APPROVAL），
与 LangChain Tool Interceptor 无关。

固定同时启用：
  - builtin：Fetch + Filesystem（目录由 mcp_allowed_directories 传入）
  - stdio：@modelcontextprotocol/server-everything
  - http：本地 streamable HTTP（默认 http://localhost:8000/mcp）

装配对齐：
  AgentConfig.mcp_servers → Agent 内部构造 MCPClient → register_tools

运行：
  # 终端 1：本地 MCP（含 business / it_operations 工具，可测 APPROVAL）
  uv run python tests/mcp_server.py

  # 终端 2：
  uv run python tests/test_react_agent_hitl_mcp.py

提示：
  - INPUT：省略必填参数即可触发
  - APPROVAL：create_refund / filesystem 写操作，话术参数齐全
"""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from typing import Any

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

# 写操作需人工审批；测 APPROVAL 时用参数齐全的话术，避免先进 INPUT
APPROVAL_REQUIRED_TOOLS = {
    "create_refund",
    "write_file",
    "edit_file",
    "move_file",
}

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


def _apply_approval_flags(registry: ToolRegistry) -> None:
    """在 MCP 注册结果上标记需审批工具（HITL APPROVAL 依赖 meta_data）。"""
    for definition in registry.list_definitions():
        original = definition.meta_data.get("original_name") or definition.name
        if original in APPROVAL_REQUIRED_TOOLS:
            definition.meta_data["required_approval"] = True


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
    _apply_approval_flags(agent.tool_registry)

    print(f"Registered {len(definitions)} MCP tools:")
    for definition in agent.tool_registry.list_definitions():
        approval = " [approval]" if definition.requires_approval else ""
        print(f"  - {definition.name} ({definition.type}){approval}")

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


def _get_pending_interrupt(agent: Agent, session_id: str) -> dict | None:
    """从 checkpoint 读取挂起的 interrupt payload。"""
    state = agent.get_state(session_id)
    interrupts = getattr(state, "interrupts", None) or ()
    if not interrupts:
        for task in getattr(state, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", None) or ()
            if task_interrupts:
                interrupts = task_interrupts
                break
    if not interrupts:
        return None
    value = interrupts[0].value
    return value if isinstance(value, dict) else None


def _collect_hitl_response(request: dict) -> dict:
    """按 HITLSubgraph interrupt payload 交互收集 resume 值。"""
    hitl_type = request.get("type")
    payload = request.get("payload", {})
    print(f"\n[HITL] {request.get('description', 'Human input required')}")
    print(f"[HITL] payload={payload}")

    if hitl_type == "input":
        fields = payload.get("fields") or {}
        tool_calls = payload.get("tool_calls") or []
        tool_name_by_id = {
            tc.get("tool_call_id"): tc.get("name") or tc.get("tool_call_id")
            for tc in tool_calls
            if tc.get("tool_call_id")
        }
        # 新协议：fields = {tool_call_id: [{name, description}, ...]}
        if isinstance(fields, dict):
            values: dict[str, Any] = {}
            for tool_call_id, call_fields in fields.items():
                tool_name = tool_name_by_id.get(tool_call_id) or tool_call_id
                print(f"  [{tool_name} / {tool_call_id}]")
                per_call: dict[str, Any] = {}
                for field in call_fields or []:
                    name = field["name"]
                    desc = field.get("description") or name
                    per_call[name] = input(f"    {name} ({desc}): ").strip()
                values[tool_call_id] = per_call
            return {"values": values}
        # 旧扁平 list 兜底
        flat_values: dict[str, Any] = {}
        for field in fields:
            name = field["name"]
            desc = field.get("description") or name
            flat_values[name] = input(f"  {name} ({desc}): ").strip()
        return {"values": flat_values}

    if hitl_type == "approval":
        approved = input("  approve? (y/n): ").strip().lower() == "y"
        return {"approved": approved}

    raise ValueError(f"unsupported HITL interrupt type: {hitl_type!r}")


async def chat_ainvoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT HITL MCP AINVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = await agent.ainvoke(session_id, UserInput(text=user_text))

        while True:
            request = _get_pending_interrupt(agent, session_id)
            if request is None:
                break
            try:
                resume_values = _collect_hitl_response(request)
            except ValueError as exc:
                print(f"[HITL] {exc}")
                break

            result = await agent.aresume(session_id, resume_values)

        print("\nAssistant:")
        print(result.get("response", result) if isinstance(result, dict) else result)
        state = agent.get_state(session_id)
        print(f"[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


async def chat_astream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT HITL MCP ASTREAM")
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

        while True:
            request = _get_pending_interrupt(agent, session_id)
            if request is None:
                break
            try:
                resume_values = _collect_hitl_response(request)
            except ValueError as exc:
                print(f"\n[HITL] {exc}")
                break

            print("\nAssistant: ", end="", flush=True)
            async for chunk in await agent.astream_resume(session_id, resume_values):
                text = extract_stream_text(chunk, node="final")
                if text:
                    print(text, end="", flush=True)

        state = agent.get_state(session_id)
        print(f"\n[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


async def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "react_hitl_mcp_test_session"

    mode = input("Choose mode (ainvoke=0 / astream=1): ").strip()
    agent_name = (
        "react_hitl_mcp_astream" if mode == "1" else "react_hitl_mcp_ainvoke"
    )
    agent, tool_registry = await build_react_agent(agent_name, config)
    print(
        "Using MCP: builtin + stdio(everything) + http(remote); "
        f"{len(tool_registry.list_definitions())} tools; "
        f"agent.mcp_client is set={agent.mcp_client is not None}"
    )
    print(f"Approval-required tools: {sorted(APPROVAL_REQUIRED_TOOLS)}")

    if mode == "1":
        await chat_astream(agent, session_id)
    else:
        await chat_ainvoke(agent, session_id)


if __name__ == "__main__":
    asyncio.run(main())
