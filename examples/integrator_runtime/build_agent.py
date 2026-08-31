"""集成方示例：用客户端 AgentConfig 组装自定义图上的 Agent。"""

from __future__ import annotations

from echo_agent import Agent, AgentConfig, BaseState, GraphSchema
from echo_agent.adapter.runtime_config import build_graph_compile_options
from echo_agent.adapter.schema import RuntimeOptions
from echo_agent.core.app import Application
from echo_agent.core.graph import END_NODE, START_NODE
from echo_agent.core.strategy import StrategyFactory, StrategyType


class _IntegratorState(BaseState):
    pass


def get_application() -> Application:
    try:
        return Application.get_application()
    except RuntimeError:
        return Application()


async def build_agent(
    config: AgentConfig,
    runtime_options: RuntimeOptions | None = None,
) -> Agent:
    """
    集成方工厂：消费 CreateAgent 下发的 AgentConfig，构建图并返回 Agent。

    本示例使用 ReAct 节点作为自定义拓扑示意；集成方用 GraphSchema
    与 Agent 构图 API（add_node / add_edge / compile）替换即可。

    ReAct 节点通过 Application.get_agent(agent_id) 取 tool_registry，
    因此必须登记到进程级 Application（两条 gRPC 入口都会走本 factory）。
    """
    compile_options = build_graph_compile_options(runtime_options)
    agent = Agent(
        config,
        GraphSchema(state_schema=_IntegratorState),
        compile_options,
    )
    get_application().add_agent(agent)

    await agent.register_mcp_tools()

    react_node = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config.llm_config,
        tool_registry=agent.tool_registry,
    )
    agent.add_node(react_node)
    agent.add_edge(START_NODE, react_node.name)
    agent.add_edge(react_node.name, END_NODE)
    agent.compile()
    return agent

