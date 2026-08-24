"""
ReAct Agent 模式（ask / agent）+ ToolAnnotations 交互测试。

覆盖：
1. 从 business_tools extras 读取 MCP ToolAnnotations 并写入 ToolDefinition
2. ASK：仅允许 readOnlyHint=true 的工具；写/删类调用会被网关拒绝
3. AGENT：允许读写与破坏性工具

运行（在 tests 目录或仓库根目录，需 tests/.env）：
  python tests/test_react_agent_mode.py
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions
from echo_agent.core.model.agent import AgentMode
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolRegistry
from echo_agent.core.tool.schema import ToolAnnotations
from env_config import build_config
from tools.business_tools import BUSINESS_TOOLS

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

MODE_CHOICES: dict[str, AgentMode] = {
    "0": AgentMode.ASK,
    "ask": AgentMode.ASK,
    "1": AgentMode.AGENT,
    "agent": AgentMode.AGENT,
}


class State(BaseState):
    pass


def _as_runnable_tool(tool_obj: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj
    return StructuredTool.from_function(tool_obj)


def _annotations_from_tool(tool_obj: Any) -> ToolAnnotations | None:
    extras = getattr(tool_obj, "extras", None) or {}
    metadata = getattr(tool_obj, "metadata", None) or {}
    raw = extras.get("annotations") or metadata.get("annotations")
    if not isinstance(raw, dict):
        return None
    return ToolAnnotations(
        read_only_hint=raw.get("readOnlyHint"),
        destructive_hint=raw.get("destructiveHint"),
        idempotent_hint=raw.get("idempotentHint"),
        open_world_hint=raw.get("openWorldHint"),
    )


def build_tool_registry(tools: Sequence[Any]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool_obj in tools:
        runnable = _as_runnable_tool(tool_obj)
        openai_tool = convert_to_openai_tool(runnable)
        fn = openai_tool["function"]
        registry.register(
            ToolDefinition(
                name=fn["name"],
                description=fn.get("description") or "",
                parameters=fn.get("parameters") or {},
                annotations=_annotations_from_tool(runnable),
            ),
            runnable,
        )
    return registry


def print_tool_annotations(registry: ToolRegistry, mode: AgentMode) -> None:
    print("\n==============================")
    print("TOOL ANNOTATIONS")
    print("==============================")
    print(
        f"{'name':<28} {'readOnly':<10} {'destructive':<12} "
        f"{'idempotent':<11} {'openWorld':<10} {'ask?'}"
    )
    for definition in registry.list_definitions():
        annotations = definition.annotations
        if annotations is None:
            read_only = destructive = idempotent = open_world = "-"
            ask_ok = "no (missing annotations)"
        else:
            read_only = str(annotations.read_only_hint)
            destructive = str(annotations.destructive_hint)
            idempotent = str(annotations.idempotent_hint)
            open_world = str(annotations.open_world_hint)
            ask_ok = "yes" if annotations.read_only_hint is True else "no"
        print(
            f"{definition.name:<28} {read_only:<10} {destructive:<12} "
            f"{idempotent:<11} {open_world:<10} {ask_ok}"
        )
    print(f"\nCurrent agent_mode: {mode.value}")
    if mode == AgentMode.ASK:
        print(
            "ASK 提示：查询类请求应走只读工具；"
            "退款 / 采购 / 删号等写操作应被拒绝（The tool cannot be invoked in the current mode.）。"
        )
    else:
        print("AGENT 提示：读写与破坏性工具均可调用。")
    print("建议用例：")
    print("  - 只读：查询张伟的用户信息和订单")
    print("  - 写入：给 order_1001 创建退款，原因：测试")
    print("  - 破坏：删除用户 u002")
    print("==============================\n")


def build_react_agent(
    name: str,
    config: LLMConfig,
    tools: Sequence[Any],
) -> tuple[Agent, ToolRegistry]:
    tool_registry = build_tool_registry(tools)
    react_subgraph = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_node(react_subgraph)
    graph.add_edge(START_NODE, react_subgraph.name)
    graph.add_edge(react_subgraph.name, END_NODE)
    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        mode=[AgentMode.ASK, AgentMode.AGENT],
        allowed_directories=str(Path(__file__).resolve().parents[1]),
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())
    return Agent(agent_config, compile_options, graph), tool_registry


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


def _print_tool_debug(agent: Agent, session_id: str) -> None:
    state = agent.get_state(session_id)
    values = state.values
    tool_state = values.get("tool_state") if isinstance(values, dict) else None
    if tool_state is None:
        print(f"[DEBUG] state values: {values}")
        return
    results = getattr(tool_state, "tool_results", None) or []
    if not results:
        print("[DEBUG] no tool_results this turn")
        return
    print("[DEBUG] tool_results:")
    for item in results:
        print(
            f"  name={item.name} success={item.success} "
            f"error={item.error!r} result={item.result!r}"
        )


def parse_turn(
    raw: str,
    current_mode: AgentMode,
) -> tuple[AgentMode, str | None] | None:
    """解析一轮输入。返回 None 表示退出；text 为 None 表示仅切模式。"""
    text = raw.strip()
    if text.lower() in {"exit", "quit"}:
        return None

    first, _, rest = text.partition(" ")
    token = first.lower().lstrip("/")
    if token in MODE_CHOICES:
        next_mode = MODE_CHOICES[token]
        leftover = rest.strip()
        return next_mode, leftover or None
    return current_mode, text


def chat_invoke(agent: Agent, session_id: str, agent_mode: AgentMode) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT MODE INVOKE")
    print("每轮可切换：/ask  /agent  （可单独输入，或 /ask 查询天气）")
    print("==============================\n")
    while True:
        raw = input(f"[{agent_mode.value}] You: ")
        parsed = parse_turn(raw, agent_mode)
        if parsed is None:
            break
        agent_mode, user_text = parsed
        if user_text is None:
            print(f"[mode] switched to {agent_mode.value}\n")
            continue
        result = agent.invoke(
            session_id,
            UserInput(text=user_text),
            agent_mode=agent_mode,
        )
        print("\nAssistant:")
        print(result.text)
        _print_tool_debug(agent, session_id)
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str, agent_mode: AgentMode) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT MODE STREAM")
    print("每轮可切换：/ask  /agent  （可单独输入，或 /ask 查询天气）")
    print("==============================\n")
    while True:
        raw = input(f"[{agent_mode.value}] You: ")
        parsed = parse_turn(raw, agent_mode)
        if parsed is None:
            break
        agent_mode, user_text = parsed
        if user_text is None:
            print(f"[mode] switched to {agent_mode.value}\n")
            continue
        print("\nAssistant: ", end="", flush=True)
        for chunk in agent.stream(
            session_id,
            UserInput(text=user_text),
            agent_mode=agent_mode,
        ):
            text = extract_stream_text(chunk, node="final")
            if text:
                print(text, end="", flush=True)
        print()
        _print_tool_debug(agent, session_id)
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "react_agent_mode_session"

    run_mode = input("Choose run (invoke=0 / stream=1): ").strip()
    agent_name = (
        "react_mode_stream" if run_mode == "1" else "react_mode_invoke"
    )
    agent, tool_registry = build_react_agent(agent_name, config, BUSINESS_TOOLS)
    print_tool_annotations(tool_registry, AgentMode.ASK)

    if run_mode == "1":
        chat_stream(agent, session_id, AgentMode.ASK)
    else:
        chat_invoke(agent, session_id, AgentMode.ASK)
