"""
ReAct + Skill 集成测试

覆盖：
1. 组装带 skill_list 的 ReAct Agent；内置 load_skill / read_skill_resource
2. 可选：LLM 对话冒烟（需 tests/.env；走 ainvoke / astream）

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
import warnings
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, UserInput
from echo_agent.core.app import Application
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions, GraphSchema
from echo_agent.core.model.agent import AgentResources, AgentState
from echo_agent.core.model.skill import SkillSource
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.strategy.react.node import ActionNode
from echo_agent.core.strategy.react.schema import ReActContext
from echo_agent.core.capability.skill import SkillManager
from echo_agent.core.tool import ToolDefinition, ToolRegistry, ToolType

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skills"
PDF_SKILL_DIR = FIXTURES / "pdf"
DEFAULT_SKILL_LIST = [SkillSource(name="pdf", url=str(PDF_SKILL_DIR))]


class State(BaseState):
    pass


async def build_react_skill_agent(
    name: str,
    config: LLMConfig,
    *,
    skill_list: dict[str, Any] | None = None,
) -> tuple[Agent, ToolRegistry]:
    """组装带 Skill 的 ReAct Agent；返回 (agent, tool_registry)。"""
    Application._instance = None
    app = Application()

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        allowed_directories=str(REPO_ROOT),
        skill_list=skill_list if skill_list is not None else dict(DEFAULT_SKILL_LIST),
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())
    agent = Agent(agent_config, GraphSchema(state_schema=State), compile_options)
    app.add_agent(agent)

    react_subgraph = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=agent.tool_registry,
    )
    agent.add_node(react_subgraph)
    agent.add_edge(START_NODE, react_subgraph.name)
    agent.add_edge(react_subgraph.name, END_NODE)
    agent.compile()
    return agent, agent.tool_registry


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

    agent, registry = await build_react_skill_agent(
        "react_skill_wiring",
        _dummy_llm_config(),
        skill_list=DEFAULT_SKILL_LIST,
    )

    assert agent._agent_config.skill_list == DEFAULT_SKILL_LIST
    names = {d.name for d in registry.list_definitions()}
    assert "load_skill" in names
    assert "read_skill_resource" in names
    print("ok")


async def test_react_skill_empty_list() -> None:
    _print("ReAct + empty skill_list")

    agent, registry = await build_react_skill_agent(
        "react_skill_empty",
        _dummy_llm_config(),
        skill_list=[],
    )
    assert agent._agent_config.skill_list == {}
    # 内置工具仍必有
    names = {d.name for d in registry.list_definitions()}
    assert "load_skill" in names
    assert "read_skill_resource" in names
    print("ok")


def test_action_tools_follow_skill_metadata() -> None:
    _print("ReAct action tool visibility")
    from echo_agent.core.model.skill import SkillFrontmatter

    registry = ToolRegistry()
    for tool in (
        ToolDefinition(name="load_skill", description="", parameters={}),
        ToolDefinition(name="read_skill_resource", description="", parameters={}),
        ToolDefinition(
            name="eicad_mcp_render_pdf",
            description="",
            parameters={},
            type=ToolType.MCP,
            meta_data={
                "mcp_server": "eicad_mcp",
                "original_name": "render_pdf",
            },
        ),
        ToolDefinition(
            name="eicad_mcp_delete_pdf",
            description="",
            parameters={},
            type=ToolType.MCP,
            meta_data={
                "mcp_server": "eicad_mcp",
                "original_name": "delete_pdf",
            },
        ),
    ):
        registry.register(tool, handler=None)

    node = ActionNode(
        name="action",
        llm_config=_dummy_llm_config(),
        tool_registry=registry,
    )
    # 有 skill_list 且未 load → 仅 meta（渐进披露）
    context = ReActContext(
        agent_state=AgentState(session_id="test"),
        resources=AgentResources(
            skill_list=DEFAULT_SKILL_LIST,
            skill_frontmatter_list=manager.build_skill_frontmatter_list(),
        ),
    )

    initial_names = {tool.name for tool in node._available_tools(context)}
    assert initial_names == {"load_skill", "read_skill_resource"}

    manager = SkillManager({"pdf": str(PDF_SKILL_DIR)})
    manager.load_skill(context, manager.build_skill_package("pdf"))
    # PDF fixture 无 allowed_tools → load 后暴露全量注册工具
    loaded_names = {tool.name for tool in node._available_tools(context)}
    assert loaded_names == {
        "load_skill",
        "read_skill_resource",
        "eicad_mcp_render_pdf",
        "eicad_mcp_delete_pdf",
    }

    # 构图后再注册的工具应对 Action 可见（活 registry，非快照）
    registry.register(
        ToolDefinition(name="late_tool", description="", parameters={}),
        handler=None,
    )
    assert "late_tool" in {tool.name for tool in node._available_tools(context)}
    print("ok")


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
        print(getattr(result, "text", result))
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
        printed = ""
        async for chunk in await agent.astream(session_id, UserInput(text=user_text)):
            text = getattr(chunk, "text", "") or ""
            delta = text[len(printed):] if text.startswith(printed) else text
            printed = text
            if delta:
                print(delta, end="", flush=True)
        state = agent.get_state(session_id)
        print(f"\n[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


async def run_unit_tests() -> None:
    assert PDF_SKILL_DIR.is_dir(), f"fixture missing: {PDF_SKILL_DIR}"
    await test_react_skill_wiring()
    await test_react_skill_empty_list()
    test_action_tools_follow_skill_metadata()
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
    print(f"skill_list: {agent._agent_config.skill_list}")

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
