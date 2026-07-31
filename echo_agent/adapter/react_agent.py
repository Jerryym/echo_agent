"""默认 ReAct Agent 组装（仅 Adapter；对齐 console MCP/ReAct 用例，不侵入 core）。"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, RootGraph
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolRegistry

from .schema import RuntimeOptions


class _AdapterState(BaseState):
    pass


def build_runtime_config(options: RuntimeOptions | None = None) -> RuntimeConfig:
    """根据 RuntimeOptions 构建 RuntimeConfig。v0.1 默认 InMemorySaver。"""
    kind = (options.checkpointer_kind if options else "memory") or "memory"
    kind = kind.strip().lower()
    if kind in ("memory", "mem", "inmemory", ""):
        return RuntimeConfig(checkpointer=InMemorySaver())
    if kind == "sqlite":
        raise ValueError(
            "checkpointer_kind=sqlite is not enabled in v0.1; use memory "
            "or add a persistence dependency in a later phase"
        )
    raise ValueError(f"unsupported checkpointer_kind: {kind!r}")


async def build_default_react_agent(
    config: AgentConfig,
    *,
    runtime_options: RuntimeOptions | None = None,
) -> Agent:
    """
    固定组装默认 ReAct Agent：

    ToolRegistry → MCP register_tools（若有）→ setup_skills
    → StrategyFactory(REACT) → RootGraph START→ReAct→END
    """
    runtime_config = build_runtime_config(runtime_options)
    tool_registry = ToolRegistry()

    placeholder = RootGraph(state_schema=_AdapterState)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(config, runtime_config, placeholder)

    if agent.mcp_client is not None:
        await agent.mcp_client.register_tools(tool_registry)

    await agent.setup_skills(tool_registry)

    react_subgraph = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config.llm_config,
        tool_registry=tool_registry,
    )
    graph = RootGraph(state_schema=_AdapterState)
    graph.add_node(react_subgraph)
    graph.add_edge(START_NODE, react_subgraph.name)
    graph.add_edge(react_subgraph.name, END_NODE)

    agent._graph = graph
    agent._compiled_graph = graph.compile(runtime_config)
    return agent
