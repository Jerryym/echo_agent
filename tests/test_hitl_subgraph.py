from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, RootGraph, UserInput
from echo_agent.common.debug import format_debug
from echo_agent.core.graph import START_NODE, END_NODE
from echo_agent.core.llm import LLMConfig
from echo_agent.core.runtime import RuntimeConfig
from echo_agent.core.runtime.human_in_the_loop import (
    HITLInput,
    HITLOutput,
    HITLState,
    HITLSubgraph,
    HITLType,
)
from echo_agent.core.runtime.human_in_the_loop.hitl_subgraph import HITLNode


class State(BaseState):
    hitl_result: dict | None = None


def _make_hitl_input(
    hitl_type: HITLType,
    user_input: UserInput | None = None,
) -> HITLInput:
    user_input = user_input or UserInput(text="")
    if hitl_type == HITLType.INPUT:
        return HITLInput(
            input=user_input,
            type=HITLType.INPUT,
            description="请补充缺失信息",
            payload={
                "fields": [
                    {"name": "city", "description": "城市"},
                    {"name": "date", "description": "日期"},
                ]
            },
        )
    return HITLInput(
        input=user_input,
        type=HITLType.APPROVAL,
        description="是否批准该操作？",
        payload={"action": "delete_resource", "risk": "high"},
    )


def build_hitl_agent(hitl_type: HITLType) -> Agent:
    hitl = HITLSubgraph()
    hitl_input = _make_hitl_input(hitl_type)
    # as_node() 当前未接收 HITLInput，测试侧直接构造 HITLNode
    hitl_node = HITLNode(name="HITL", hitl=hitl, input=hitl_input)

    graph = RootGraph(state_schema=State)
    graph.add_node(hitl_node)
    graph.add_edge(START_NODE, hitl_node.name)
    graph.add_edge(hitl_node.name, END_NODE)

    # AgentConfig 强制要 llm_config，这里给占位即可（本图不用 LLM）
    agent_config = AgentConfig(
        name=f"hitl_only_{hitl_type.value}",
        description="HITLSubgraph unit harness",
        llm_config=LLMConfig(
            base_url="http://localhost",
            api_key="unused",
            model_name="unused",
        ),
    )
    runtime_config = RuntimeConfig(checkpointer=InMemorySaver())
    return Agent(agent_config, runtime_config, graph)


def get_pending_interrupt(agent: Agent, session_id: str) -> dict | None:
    state = agent.get_state(session_id)
    interrupts = getattr(state, "interrupts", None) or ()
    if not interrupts:
        for task in getattr(state, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", None) or ()
            if task_interrupts:
                interrupts = task_interrupts
                break
    if not interrupts:
        return None
    value = interrupts[0].value
    return value if isinstance(value, dict) else None


# ---------- 1) 无 interrupt 的单元断言 ----------

def test_type_router_and_mapping():
    hitl = HITLSubgraph()

    # to_hitl_state：由 HITLInput 构造 HITLState
    hitl_input = HITLInput(
        input=UserInput(text="hello"),
        type=HITLType.INPUT,
        description="need info",
        payload={"fields": []},
    )
    mapped = hitl.to_hitl_state(hitl_input)
    assert mapped.type == HITLType.INPUT
    assert mapped.description == "need info"
    assert mapped.status == "pending"
    assert mapped.id

    # _type_router
    assert hitl._type_router(
        HITLState(type=HITLType.INPUT, description="d")
    ) == "input_flow"
    assert hitl._type_router(
        HITLState(type=HITLType.APPROVAL, description="d")
    ) == "approval_flow"

    # to_parent_state
    out = HITLOutput(id="abc", status="completed", result={"ok": True})
    assert hitl.to_parent_state(out) == {
        "hitl_result": {"id": "abc", "status": "completed", "result": {"ok": True}}
    }


# ---------- 2) 端到端：INPUT ----------

def test_input_flow_interrupt_resume():
    session_id = "hitl_input_session"
    agent = build_hitl_agent(HITLType.INPUT)

    agent.invoke(session_id, UserInput(text="trigger input hitl"))
    request = get_pending_interrupt(agent, session_id)
    assert request is not None
    assert request["type"] == "input"
    assert "fields" in request["payload"]

    result = agent.resume(
        session_id,
        {"values": {"city": "Shanghai", "date": "2026-07-16"}},
    )
    assert result["hitl_result"]["status"] == "completed"
    assert result["hitl_result"]["result"] == {
        "values": {"city": "Shanghai", "date": "2026-07-16"}
    }
    assert get_pending_interrupt(agent, session_id) is None


# ---------- 3) 端到端：APPROVAL ----------

def test_approval_flow_interrupt_resume():
    session_id = "hitl_approval_session"
    agent = build_hitl_agent(HITLType.APPROVAL)

    agent.invoke(session_id, UserInput(text="trigger approval hitl"))
    request = get_pending_interrupt(agent, session_id)
    assert request is not None
    assert request["type"] == "approval"

    result = agent.resume(session_id, {"approved": True, "reason": "lgtm"})
    assert result["hitl_result"]["status"] == "completed"
    assert result["hitl_result"]["result"]["approved"] is True


# ---------- 可选：交互式脚本 ----------

def chat_hitl(hitl_type: HITLType) -> None:
    agent = build_hitl_agent(hitl_type)
    session_id = f"hitl_chat_{hitl_type.value}"
    print(f"HITL type={hitl_type.value}. type 'exit' to quit.")

    while True:
        text = input("You: ").strip()
        if text.lower() in {"exit", "quit"}:
            break

        result = agent.invoke(session_id, UserInput(text=text))
        while True:
            request = get_pending_interrupt(agent, session_id)
            if request is None:
                break
            print(f"\n[HITL] {request.get('description')}")
            print(f"[HITL] payload={request.get('payload')}")
            if request.get("type") == "input":
                fields = request.get("payload", {}).get("fields") or {}
                values: dict[str, Any] = {}
                if isinstance(fields, dict):
                    for tool_call_id, call_fields in fields.items():
                        print(f"  [{tool_call_id}]")
                        per_call: dict[str, Any] = {}
                        for field in call_fields or []:
                            per_call[field["name"]] = input(
                                f"    {field['name']}: "
                            ).strip()
                        values[tool_call_id] = per_call
                else:
                    for field in fields:
                        values[field["name"]] = input(f"  {field['name']}: ").strip()
                resume_values: dict[str, Any] = {"values": values}
            else:
                approved = input("  approve? (y/n): ").strip().lower() == "y"
                resume_values = {"approved": approved}
            result = agent.resume(session_id, resume_values)

        print("[HITL] result:", format_debug(result["hitl_result"]))
        print("-" * 40)


if __name__ == "__main__":
    # 不跑 pytest 时，交互验证
    mode = input("type (input=0 / approval=1): ").strip()
    chat_hitl(HITLType.INPUT if mode != "1" else HITLType.APPROVAL)
