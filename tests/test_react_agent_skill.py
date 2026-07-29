"""
ReAct + Skill 集成测试

覆盖：
1. 组装 ReAct Agent 并 setup_skills（pdf fixture）
2. ToolRegistry 含 load_skill / read_skill_resource
3. 经 ToolExecutor 执行 Skill 工具（无需 LLM）
4. 可选：LLM 对话冒烟（需 tests/.env；走 ainvoke / astream）

运行：
  # 仅自动化接线测试（默认）
  python tests/test_react_agent_skill.py

  # 进入对话（需配置 LLM）
  python tests/test_react_agent_skill.py
  # 选择 chat=1，再选 ainvoke=0 / astream=1
"""

from __future__ import annotations

import asyncio
import sys
import uuid
import warnings
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.capability.skill import get_active_catalog, set_active_catalog
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.model import ToolCall
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolExecutor, ToolRegistry

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"
PDF_SKILL_DIR = FIXTURES / "pdf"
DEFAULT_SKILL_LIST = {"pdf": str(PDF_SKILL_DIR)}


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


async def build_react_skill_agent(
    name: str,
    config: LLMConfig,
    *,
    skill_list: dict[str, Any] | None = None,
    extra_tools: Sequence[Any] | None = None,
) -> tuple[Agent, ToolRegistry]:
    """组装带 Skill 的 ReAct Agent；返回 (agent, tool_registry)。"""
    tool_registry = build_tool_registry(extra_tools or [])
    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        mcp_allowed_directories=str(REPO_ROOT),
        skill_list=skill_list if skill_list is not None else dict(DEFAULT_SKILL_LIST),
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())

    placeholder = RootGraph(state_schema=State)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(agent_config, runtime_config, placeholder)

    skill_prompt = await agent.setup_skills(tool_registry)
    assert skill_prompt is not None or not agent_config.skill_list

    react_subgraph = StrategyFactory.create_as_subgraph(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_subgraph("ReAct", react_subgraph)
    graph.add_edge(START_NODE, "ReAct")
    graph.add_edge("ReAct", END_NODE)

    agent._graph = graph
    agent._compiled_graph = graph.compile(runtime_config)
    return agent, tool_registry


def _print(title: str) -> None:
    print(f"\n=== {title} ===")


def _dummy_llm_config() -> LLMConfig:
    """接线测试不调用模型，仅满足 AgentConfig 必填。"""
    return LLMConfig(
        base_url="http://localhost",
        api_key="test",
        model_name="test-model",
        model_provider="openai",
    )


async def test_react_skill_wiring() -> None:
    _print("ReAct + Skill wiring")
    set_active_catalog(None)

    agent, registry = await build_react_skill_agent(
        "react_skill_wiring",
        _dummy_llm_config(),
        skill_list=DEFAULT_SKILL_LIST,
    )

    catalog = agent.skill_catalog
    assert catalog is not None
    assert len(catalog) == 1
    assert catalog.get("pdf") is not None
    assert get_active_catalog() is catalog

    names = {d.name for d in registry.list_definitions()}
    assert "load_skill" in names
    assert "read_skill_resource" in names

    set_active_catalog(None)
    print("ok")


async def test_react_skill_tool_executor() -> None:
    _print("ReAct + Skill ToolExecutor")
    set_active_catalog(None)

    _agent, registry = await build_react_skill_agent(
        "react_skill_executor",
        _dummy_llm_config(),
        skill_list=DEFAULT_SKILL_LIST,
    )
    executor = ToolExecutor(registry)

    load_result = await executor.aexecute(
        ToolCall(
            name="load_skill",
            args={"name": "pdf"},
            tool_call_id=str(uuid.uuid4()),
        )
    )
    assert load_result.success is True
    assert "# PDF Skill" in str(load_result.result)
    assert "name: pdf" not in str(load_result.result)

    read_result = await executor.aexecute(
        ToolCall(
            name="read_skill_resource",
            args={"name": "pdf", "path": "references/specification.md"},
            tool_call_id=str(uuid.uuid4()),
        )
    )
    assert read_result.success is True
    assert "UTF-8" in str(read_result.result)

    unknown = await executor.aexecute(
        ToolCall(
            name="load_skill",
            args={"name": "missing"},
            tool_call_id=str(uuid.uuid4()),
        )
    )
    assert unknown.success is True
    assert "Unknown skill" in str(unknown.result)

    set_active_catalog(None)
    print("ok")


async def test_react_skill_empty_list() -> None:
    _print("ReAct + empty skill_list")
    set_active_catalog(None)

    agent, registry = await build_react_skill_agent(
        "react_skill_empty",
        _dummy_llm_config(),
        skill_list={},
    )
    assert agent.skill_catalog is not None
    assert len(agent.skill_catalog) == 0
    names = {d.name for d in registry.list_definitions()}
    assert "load_skill" not in names
    assert "read_skill_resource" not in names

    set_active_catalog(None)
    print("ok")


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
    print("TEST: REACT + SKILL AINVOKE")
    print("Hint: try「请先加载 pdf skill，并阅读 references/specification.md」")
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
    print("TEST: REACT + SKILL ASTREAM")
    print("Hint: try「请先加载 pdf skill，并阅读 references/specification.md」")
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


async def run_unit_tests() -> None:
    assert PDF_SKILL_DIR.is_dir(), f"fixture missing: {PDF_SKILL_DIR}"
    await test_react_skill_wiring()
    await test_react_skill_tool_executor()
    await test_react_skill_empty_list()
    print("\nAll ReAct + Skill unit tests passed.")


async def run_chat() -> None:
    from env_config import build_config

    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    mode = input("Choose mode (ainvoke=0 / astream=1): ").strip()
    agent, registry = await build_react_skill_agent(
        "react_skill_chat",
        config,
        skill_list=DEFAULT_SKILL_LIST,
    )
    tool_names = [d.name for d in registry.list_definitions()]
    print(f"Tools: {tool_names}")
    print(f"Skills: {[s.name for s in (agent.skill_catalog.list() if agent.skill_catalog else [])]}")

    session_id = "react_skill_session"
    if mode == "1":
        await chat_astream(agent, session_id)
    else:
        await chat_ainvoke(agent, session_id)


def main() -> None:
    # 非交互：python tests/test_react_agent_skill.py --unit
    if "--unit" in sys.argv or not sys.stdin.isatty():
        asyncio.run(run_unit_tests())
        return

    choice = input("Choose (unit=0 / chat=1) [0]: ").strip() or "0"
    if choice == "1":
        asyncio.run(run_chat())
    else:
        asyncio.run(run_unit_tests())


if __name__ == "__main__":
    main()
