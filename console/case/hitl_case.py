from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseContext, BaseState, Node, RootGraph, UserInput
from echo_agent.core.graph import START_NODE, END_NODE
from echo_agent.core.model.hitl import HITLInput, HITLType
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.runtime.human_in_the_loop import HITLSubgraph

from case.base import BaseCase, CaseResult
from case.common import extract_reply, get_pending_interrupt
from case.env_config import placeholder_config


class State(BaseState):
    pass


class PrepareHITLNode(Node):
    """写入 hitl_request，再交给 HITL 节点 interrupt。"""

    def run(self, state: State, context: BaseContext | None = None, config=None) -> dict:
        text = ""
        if isinstance(state.input, UserInput):
            text = state.input.text or ""
        elif isinstance(state.input, str):
            text = state.input

        hitl_type = HITLType.APPROVAL if "approval" in text.lower() else HITLType.INPUT
        if hitl_type == HITLType.INPUT:
            request = HITLInput(
                type=HITLType.INPUT,
                description="请补充缺失信息",
                payload={
                    "fields": [
                        {"name": "city", "description": "城市"},
                        {"name": "date", "description": "日期"},
                    ]
                },
            )
        else:
            request = HITLInput(
                type=HITLType.APPROVAL,
                description="是否批准该操作？",
                payload={"action": "delete_resource", "risk": "high"},
            )
        return {"hitl_request": request}

    async def arun(self, state: State, context: BaseContext | None = None, config=None) -> dict:
        raise NotImplementedError("PrepareHITLNode is sync-only")


def build_hitl_agent() -> Agent:
    prepare = PrepareHITLNode("prepare_hitl")
    hitl_node = HITLSubgraph().as_node()

    graph = RootGraph(state_schema=State)
    graph.add_node(prepare)
    graph.add_node(hitl_node)
    graph.add_edge(START_NODE, prepare.name)
    graph.add_edge(prepare.name, hitl_node.name)
    graph.add_edge(hitl_node.name, END_NODE)

    agent_config = AgentConfig(
        name="console_hitl_only",
        description="HITLSubgraph harness (no LLM)",
        llm_config=placeholder_config(),
        mcp_allowed_directories=str(Path(__file__).resolve().parents[2]),
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


class HITLCase(BaseCase):
    """纯 HITL 子图测试（无需接入模型）。

    - 普通消息 → INPUT 补参表单
    - 消息含 approval → APPROVAL 表单
    """

    name = "hitl"
    title = "HITL Subgraph"
    strategy = "None"

    def create_runtime(self, llm_config=None) -> Agent:
        return build_hitl_agent()

    def on_message(self, runtime: Agent, session_id: str, text: str) -> CaseResult:
        result = runtime.invoke(session_id, UserInput(text=text))
        return self._to_result(runtime, session_id, result)

    def on_hitl(self, runtime: Agent, session_id: str, values: dict) -> CaseResult:
        result = runtime.resume(session_id, values)
        return self._to_result(runtime, session_id, result)

    def _to_result(self, runtime: Agent, session_id: str, result) -> CaseResult:
        pending = get_pending_interrupt(runtime, session_id)
        if pending is not None:
            return CaseResult(
                pending_hitl=pending,
                debug=f"hitl pending type={pending.get('type')}",
            )
        reply = extract_reply(result)
        state = runtime.get_state(session_id)
        return CaseResult(
            reply=reply or "HITL completed",
            debug=f"state={getattr(state, 'values', state)}",
        )
