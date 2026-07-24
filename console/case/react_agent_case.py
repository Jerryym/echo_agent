from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, RootGraph, UserInput
from echo_agent.core.graph import START_NODE, END_NODE
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.strategy import StrategyFactory, StrategyType
from case.base import BaseCase, CaseResult
from case.common import (
    build_tool_registry,
    ensure_tests_tools_path,
    extract_reply,
    get_pending_interrupt,
)

REPO_ROOT = str(Path(__file__).resolve().parents[2])


class State(BaseState):
    pass


def build_react_agent(
    name: str,
    config: LLMConfig,
    *,
    approval_required: set[str] | None = None,
    skill_list: dict | None = None,
) -> Agent:
    ensure_tests_tools_path()
    from tools.business_tools import BUSINESS_TOOLS

    return asyncio.run(
        _abuild_react_agent(
            name,
            config,
            approval_required=approval_required,
            skill_list=skill_list,
            business_tools=BUSINESS_TOOLS,
        )
    )


async def _abuild_react_agent(
    name: str,
    config: LLMConfig,
    *,
    approval_required: set[str] | None,
    skill_list: dict | None,
    business_tools,
) -> Agent:
    tool_registry = build_tool_registry(
        business_tools,
        approval_required=approval_required,
    )
    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        mcp_allowed_directories=REPO_ROOT,
        skill_list=skill_list or {},
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())

    placeholder = RootGraph(state_schema=State)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(agent_config, runtime_config, placeholder)

    await agent.setup_skills(tool_registry)

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
    return agent


class ReactAgentCase(BaseCase):
    """ReAct Agent（无 HITL / 无审批工具）。"""

    name = "react_agent"
    title = "ReAct（无HITL）"
    strategy = "ReAct"

    def create_runtime(self, llm_config: LLMConfig | None) -> Agent:
        if llm_config is None:
            raise ValueError("ReAct Case 需要 llm_config")
        return build_react_agent("console_react", llm_config, approval_required=None)

    def on_message(self, runtime: Agent, session_id: str, text: str) -> CaseResult:
        result = runtime.invoke(session_id, UserInput(text=text))
        pending = get_pending_interrupt(runtime, session_id)
        if pending is not None:
            return CaseResult(
                pending_hitl=pending,
                debug=f"unexpected hitl in no-HITL case: {pending}",
            )
        reply = extract_reply(result)
        state = runtime.get_state(session_id)
        return CaseResult(reply=reply, debug=f"state={getattr(state, 'values', state)}")
