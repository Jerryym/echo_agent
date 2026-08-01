"""Console MCP 相关公共装配：builtin + stdio + http。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.mcp import MCPConnectionConfig
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType

REPO_ROOT = str(Path(__file__).resolve().parents[2])
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

# HITL APPROVAL：http create_refund + filesystem 写操作
APPROVAL_REQUIRED_TOOLS = {
    "create_refund",
    "write_file",
    "edit_file",
    "move_file",
}


class State(BaseState):
    pass


@dataclass
class MCPRuntimeHolder:
    """延迟创建 Agent：首次消息在 CaseWorker 线程中完成 MCP 注册。"""

    name: str
    llm_config: LLMConfig
    approval_required: set[str] | None = None
    agent: Agent | None = None
    tool_names: list[str] = field(default_factory=list)

    def ensure_agent(self) -> Agent:
        if self.agent is None:
            self.agent, self.tool_names = build_react_mcp_agent(
                self.name,
                self.llm_config,
                approval_required=self.approval_required,
            )
        return self.agent


def apply_approval_flags(
    registry: ToolRegistry,
    approval_required: set[str] | None,
) -> None:
    if not approval_required:
        return
    for definition in registry.list_definitions():
        original = definition.meta_data.get("original_name") or definition.name
        if original in approval_required:
            definition.meta_data["required_approval"] = True


def build_react_mcp_agent(
    name: str,
    llm_config: LLMConfig,
    *,
    approval_required: set[str] | None = None,
) -> tuple[Agent, list[str]]:
    """
    同步封装：内置 MCP + stdio/http → register_tools → ReAct 图。
    """
    return asyncio.run(
        _abuild_react_mcp_agent(
            name,
            llm_config,
            approval_required=approval_required,
        )
    )


async def _abuild_react_mcp_agent(
    name: str,
    llm_config: LLMConfig,
    *,
    approval_required: set[str] | None = None,
) -> tuple[Agent, list[str]]:
    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=llm_config,
        mcp_allowed_directories=REPO_ROOT,
        mcp_servers=list(MCP_SERVERS),
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())

    placeholder = RootGraph(state_schema=State)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(agent_config, runtime_config, placeholder)
    if agent.mcp_client is None:
        raise RuntimeError("MCPClient 未创建：检查 AgentConfig.mcp_servers")

    await agent.register_mcp_tools()
    apply_approval_flags(agent.tool_registry, approval_required)

    react_subgraph = StrategyFactory.create_as_subgraph(
        StrategyType.REACT,
        llm_config=llm_config,
        tool_registry=agent.tool_registry,
    )
    graph = RootGraph(state_schema=State)
    graph.add_subgraph("ReAct", react_subgraph)
    graph.add_edge(START_NODE, "ReAct")
    graph.add_edge("ReAct", END_NODE)

    agent._graph = graph
    agent._compiled_graph = graph.compile(runtime_config)

    tool_names = [d.name for d in agent.tool_registry.list_definitions()]
    return agent, tool_names


def run_async(coro):
    """在 CaseWorker 线程中跑协程（ainvoke / aresume）。"""
    return asyncio.run(coro)
