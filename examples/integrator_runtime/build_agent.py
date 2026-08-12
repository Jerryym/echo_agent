"""集成方示例：用客户端 AgentConfig 组装自定义图上的 Agent。"""

from __future__ import annotations

from echo_agent import Agent, AgentConfig, BaseState, RootGraph
from echo_agent.adapter.runtime_config import build_graph_compile_options
from echo_agent.adapter.schema import RuntimeOptions
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.strategy import StrategyFactory, StrategyType


class _IntegratorState(BaseState):
    pass


async def build_agent(
    config: AgentConfig,
    runtime_options: RuntimeOptions | None = None,
) -> Agent:
    """
    集成方工厂：消费 CreateAgent 下发的 AgentConfig，构建图并返回 Agent。

    本示例使用 ReAct 子图作为自定义拓扑示意；集成方可替换为任意 RootGraph。
    """
    compile_options = build_graph_compile_options(runtime_options)

    placeholder = RootGraph(state_schema=_IntegratorState)
    placeholder.add_edge(START_NODE, END_NODE)
    agent = Agent(config, compile_options, placeholder)

    await agent.register_mcp_tools()

    react_node = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config.llm_config,
        tool_registry=agent.tool_registry,
    )
    graph = RootGraph(state_schema=_IntegratorState)
    graph.add_node(react_node)
    graph.add_edge(START_NODE, react_node.name)
    graph.add_edge(react_node.name, END_NODE)

    agent._graph = graph
    agent._compiled_graph = graph.compile(compile_options)
    return agent
