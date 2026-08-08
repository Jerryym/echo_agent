"""
ReAct Agent + Adapter reasoning/content 事件 交互式真实联调

运行:
  python tests/test_react_agent_reasoning.py

流式模式下按 chunk 映射 AgentEvent：
  - 有 reasoning → event:reasoning
  - 无 reasoning → 发送 content（event:message）
并打印 raw 消息内容。

注意：ReAct 节点仅注册异步实现，须走 ainvoke / astream。
"""

from __future__ import annotations

import asyncio
import json
import warnings
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.adapter.events import iter_agent_events, map_stream_chunk
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolRegistry

from env_config import build_config
from tools.business_tools import BUSINESS_TOOLS
from tools.it_operations_tool import IT_OPERATIONS_TOOLS

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

TOOL_SETS: dict[str, tuple[str, Sequence[Any]]] = {
    "0": ("business", BUSINESS_TOOLS),
    "1": ("it_operations", IT_OPERATIONS_TOOLS),
}


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


def select_tool_set() -> tuple[str, Sequence[Any]]:
    print("Available tool sets:")
    for key, (name, tools) in TOOL_SETS.items():
        print(f"  {key}: {name} ({len(tools)} tools)")
    choice = input("Choose tool set (business=0 / it_operations=1): ").strip()
    if choice not in TOOL_SETS:
        print(f"Unknown choice {choice!r}, fallback to business.")
        choice = "0"
    return TOOL_SETS[choice]


def build_react_agent(name: str, config: LLMConfig, tools: Sequence[Any]) -> Agent:
    tool_registry = build_tool_registry(tools)
    react_node = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_node(react_node)
    graph.add_edge(START_NODE, react_node.name)
    graph.add_edge(react_node.name, END_NODE)

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        mcp_allowed_directories=str(Path(__file__).resolve().parents[1]),
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


def _preview(value: object, limit: int = 2000) -> str:
    text = repr(value)
    if len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


def _dump_raw_from_chunk(chunk: Any) -> None:
    """从 Agent.astream chunk 解包并打印 raw 消息。"""
    events = map_stream_chunk(chunk)
    # 再解包一次用于打印原始 message
    from echo_agent.adapter.events import _unwrap_message

    message = _unwrap_message(chunk)
    print("\n[raw chunk]")
    if message is None:
        print(f"  unparsed chunk type={type(chunk).__name__} value={_preview(chunk, 400)}")
        return
    print(f"  message_type={type(message).__name__}")
    content = getattr(message, "content", None)
    print(f"  content type={type(content).__name__}")
    print(f"  content={_preview(content)}")
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        print(f"  tool_calls={_preview(tool_calls, 500)}")
    if events:
        print("  mapped events:")
        for event in events:
            print(
                f"    type={event.type} "
                f"data={json.dumps(event.data, ensure_ascii=False)[:400]}"
            )


async def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in {"exit", "quit"}:
            break

        result = await agent.ainvoke(session_id, UserInput(text=user_text))
        response = result.get("response", result) if isinstance(result, dict) else result
        # invoke 无 messages 流；有最终回复则作为 content 展示
        if response:
            print(f"\n[content]\n{response}")
        else:
            print("\n[content] (empty)")
        state = agent.get_state(session_id)
        print(f"\n[raw state.values]\n{_preview(getattr(state, 'values', state))}")
        print("\n------------------------------\n")


async def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT STREAM → AgentEvent")
    print("==============================\n")
    print("Tips: exit/quit 结束；每轮打印 reasoning/message 事件与 raw。\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in {"exit", "quit"}:
            break

        print("\n--- stream ---")
        stream = await agent.astream(session_id, UserInput(text=user_text))
        async for event in iter_agent_events(agent, session_id, stream):
            if event.type == "reasoning":
                print(f"\n[event:reasoning]\n{event.data.get('text', '')}")
            elif event.type == "message":
                role = event.data.get("role")
                content = event.data.get("content") or ""
                # 无 reasoning 时前端依赖 content
                if content:
                    print(f"\n[event:message role={role}]\n{content}")
                tool_calls = event.data.get("tool_calls")
                if tool_calls:
                    print(f"[tool_calls] {_preview(tool_calls, 400)}")
            elif event.type == "tool_result":
                print(
                    f"\n[event:tool_result] "
                    f"name={event.data.get('name')} "
                    f"content={_preview(event.data.get('content'), 400)}"
                )
            elif event.type == "interrupt":
                print(f"\n[event:interrupt]\n{_preview(event.data)}")
            elif event.type == "done":
                print(f"\n[event:done] output={event.data.get('output', '')}")
            elif event.type == "error":
                print(f"\n[event:error] {event.data}")
            else:
                print(f"\n[event:{event.type}] {_preview(event.data)}")

        # 再跑一轮仅用于对照 raw（上面 iter 已消费 stream，这里打 state）
        state = agent.get_state(session_id)
        print(f"\n[raw state.values]\n{_preview(getattr(state, 'values', state))}")
        print("\n------------------------------\n")


async def chat_stream_with_raw(agent: Agent, session_id: str) -> None:
    """流式：逐 chunk 打印 raw + 映射事件（更利于排查 reasoning block）。"""
    print("\n==============================")
    print("TEST: REACT AGENT STREAM (raw + events)")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in {"exit", "quit"}:
            break

        print("\n--- stream chunks ---")
        saw_reasoning = False
        last_message_content = ""
        stream = await agent.astream(session_id, UserInput(text=user_text))
        async for chunk in stream:
            _dump_raw_from_chunk(chunk)
            for event in map_stream_chunk(chunk):
                if event.type == "reasoning":
                    saw_reasoning = True
                    print(f"\n>> SEND reasoning:\n{event.data.get('text', '')}")
                elif event.type == "message" and event.data.get("content"):
                    last_message_content = str(event.data.get("content") or "")
                    print(f"\n>> SEND message content:\n{last_message_content}")

        if not saw_reasoning:
            print(
                f"\n>> NO reasoning in stream; last content fallback:\n"
                f"{last_message_content or '(empty)'}"
            )

        pending = None
        try:
            from echo_agent.adapter.events import get_pending_interrupt

            pending = get_pending_interrupt(agent, session_id)
        except Exception:
            pending = None
        if pending:
            print(f"\n[interrupt] {_preview(pending)}")
        else:
            state = agent.get_state(session_id)
            values = getattr(state, "values", {}) or {}
            print(f"\n[done] response={values.get('response', '')}")

        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    print(
        f"model={config.model_name} provider={config.model_provider} "
        f"extra_body={config.extra_body}"
    )

    tool_set_name, tools = select_tool_set()
    session_id = "react_reasoning_session"
    mode = input(
        "Choose mode (invoke=0 / stream-events=1 / stream-raw=2): "
    ).strip()

    agent = build_react_agent(
        f"react_reasoning_{tool_set_name}_{mode or '0'}",
        config,
        tools,
    )
    print(f"Using tool set: {tool_set_name} ({len(tools)} tools)")

    if mode == "1":
        asyncio.run(chat_stream(agent, session_id))
    elif mode == "2":
        asyncio.run(chat_stream_with_raw(agent, session_id))
    else:
        asyncio.run(chat_invoke(agent, session_id))
