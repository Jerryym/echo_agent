"""AgentResult / Adapter 映射集成测试（真实 LLM，交互式）。"""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.adapter.events import iter_agent_events, iter_agent_events_sync
from echo_agent.core.app import Application
from echo_agent.core.graph import START_NODE, END_NODE, GraphCompileOptions
from echo_agent.core.model.agent import AgentResult
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolRegistry
from env_config import build_config
from tools.business_tools import BUSINESS_TOOLS

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

REPO_ROOT = str(Path(__file__).resolve().parents[1])


class State(BaseState):
    pass


def _as_runnable_tool(tool_obj: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj
    return StructuredTool.from_function(tool_obj)


def build_tool_registry(tools: Sequence[Any]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool_obj in tools:
        runnable = _as_runnable_tool(tool_obj)
        tool = convert_to_openai_tool(runnable)
        fn = tool["function"]
        registry.register(
            ToolDefinition(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"],
            ),
            runnable,
        )
    return registry


def build_react_agent(name: str, config: LLMConfig, tools: Sequence[Any]) -> Agent:
    Application._instance = None
    app = Application()

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        allowed_directories=REPO_ROOT,
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())

    placeholder = RootGraph(state_schema=State)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(agent_config, compile_options, placeholder)
    app.add_agent(agent)

    business_registry = build_tool_registry(tools)
    for definition in business_registry.list_definitions():
        agent.tool_registry.register(
            definition,
            business_registry.get_handler(definition.name),
        )

    react_node = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=agent.tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_node(react_node)
    graph.add_edge(START_NODE, react_node.name)
    graph.add_edge(react_node.name, END_NODE)
    agent._graph = graph
    agent._compiled_graph = graph.compile(compile_options)
    return agent


def _print_agent_result(result: AgentResult, *, title: str = "AgentResult") -> None:
    print(f"\n--- {title} ---")
    print(f"text: {result.text!r}")
    print(f"reasoning ({len(result.reasoning)}):")
    for i, item in enumerate(result.reasoning, 1):
        preview = item if len(item) <= 400 else item[:400] + "..."
        print(f"  [{i}] {preview}")
    usage = result.token_usage
    print(
        f"token_usage: input={usage.input_tokens} "
        f"output={usage.output_tokens} total={usage.total_tokens}"
    )


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT RESULT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = agent.invoke(session_id, UserInput(text=user_text))
        assert isinstance(result, AgentResult)
        _print_agent_result(result, title="invoke return")

        archived = agent.get_agent_results(session_id)
        print(f"archived rounds: {len(archived)}")
        if archived:
            _print_agent_result(archived[-1], title="archived last")

        session_usage = agent._get_agent_state(session_id).token_usage
        print(
            f"session token_usage total={session_usage.total_tokens} "
            f"(input={session_usage.input_tokens} output={session_usage.output_tokens})"
        )
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT RESULT STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nStreaming AgentResult snapshots:")
        last: AgentResult | None = None
        for i, snapshot in enumerate(agent.stream(session_id, UserInput(text=user_text)), 1):
            assert isinstance(snapshot, AgentResult)
            last = snapshot
            print(
                f"  #{i} reasoning={len(snapshot.reasoning)} "
                f"text_len={len(snapshot.text)} "
                f"tokens={snapshot.token_usage.total_tokens}"
            )
            if snapshot.reasoning:
                preview = snapshot.reasoning[-1]
                if len(preview) > 160:
                    preview = preview[:160] + "..."
                print(f"       last_reasoning: {preview}")

        if last is not None:
            _print_agent_result(last, title="final snapshot")
        archived = agent.get_agent_results(session_id)
        print(f"archived rounds: {len(archived)}")
        print("\n------------------------------\n")


def chat_astream_adapter(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT RESULT ASTREAM → Adapter events")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        async def _run() -> None:
            stream = await agent.astream(session_id, UserInput(text=user_text))
            async for event in iter_agent_events(agent, session_id, stream):
                if event.type == "agent_result":
                    data = event.data
                    print(
                        f"  [agent_result] reasoning={len(data.get('reasoning') or [])} "
                        f"text_len={len(data.get('text') or '')} "
                        f"tokens={(data.get('token_usage') or {}).get('total_tokens')}"
                    )
                elif event.type == "interrupt":
                    print(f"  [interrupt] {event.data}")
                elif event.type == "done":
                    print(f"  [done] output={event.data.get('output')!r}")
                    if event.data.get("agent_result"):
                        ar = event.data["agent_result"]
                        print(
                            f"         reasoning={len(ar.get('reasoning') or [])} "
                            f"tokens={(ar.get('token_usage') or {}).get('total_tokens')}"
                        )
                elif event.type == "error":
                    print(f"  [error] {event.data}")
                else:
                    print(f"  [{event.type}] {event.data}")

        asyncio.run(_run())
        print(f"archived rounds: {len(agent.get_agent_results(session_id))}")
        print("\n------------------------------\n")


def chat_stream_adapter_sync(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: AGENT RESULT STREAM → Adapter events (sync)")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        stream = agent.stream(session_id, UserInput(text=user_text))
        for event in iter_agent_events_sync(agent, session_id, stream):
            if event.type == "agent_result":
                data = event.data
                print(
                    f"  [agent_result] reasoning={len(data.get('reasoning') or [])} "
                    f"text_len={len(data.get('text') or '')}"
                )
            elif event.type == "done":
                print(f"  [done] output={event.data.get('output')!r}")
            elif event.type == "interrupt":
                print(f"  [interrupt] {event.data}")
            else:
                print(f"  [{event.type}] {event.data}")
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "agent_result_test_session"
    agent = build_react_agent("agent_result_react", config, BUSINESS_TOOLS)

    print("Modes:")
    print("  0: invoke → AgentResult")
    print("  1: stream → Iterator[AgentResult]")
    print("  2: astream → Adapter AgentEvent")
    print("  3: stream → Adapter AgentEvent (sync)")
    mode = input("Choose mode: ").strip()

    if mode == "1":
        chat_stream(agent, session_id)
    elif mode == "2":
        chat_astream_adapter(agent, session_id)
    elif mode == "3":
        chat_stream_adapter_sync(agent, session_id)
    else:
        chat_invoke(agent, session_id)
