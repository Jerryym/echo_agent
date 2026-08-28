import asyncio
from pathlib import Path
from typing import Any, Sequence
import warnings

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, UserInput
from echo_agent.core.app import Application
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions, GraphSchema
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolDefinition, ToolRegistry
from env_config import build_config
from tools.business_tools import BUSINESS_TOOLS
from tools.export_tool_schema import export_tool_json_schema
from tools.it_operations_tool import IT_OPERATIONS_TOOLS

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

TOOL_SETS: dict[str, tuple[str, Sequence[Any]]] = {
    "0": ("business", BUSINESS_TOOLS),
    "1": ("it_operations", IT_OPERATIONS_TOOLS),
}

# 写操作需人工审批；测 APPROVAL 时用参数齐全的话术，避免先进 INPUT
APPROVAL_REQUIRED_TOOLS = {
    "create_refund",
}


class State(BaseState):
    pass


def _as_runnable_tool(tool_obj: Any) -> Any:
    """确保 handler 具备 ToolExecutor 所需的 invoke 接口。"""
    if hasattr(tool_obj, "invoke"):
        return tool_obj
    return StructuredTool.from_function(tool_obj)


def build_tool_registry(tools: Sequence[Any]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool_obj in tools:
        runnable = _as_runnable_tool(tool_obj)
        tool = convert_to_openai_tool(runnable)
        fn = tool["function"]
        name = fn["name"]
        registry.register(
            ToolDefinition(
                name=name,
                description=fn["description"],
                parameters=fn["parameters"],
                meta_data={
                    "required_approval": name in APPROVAL_REQUIRED_TOOLS,
                },
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
    Application._instance = None
    app = Application()

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        allowed_directories=str(Path(__file__).resolve().parents[1]),
    )
    compile_options = GraphCompileOptions(checkpointer=InMemorySaver())
    agent = Agent(agent_config, GraphSchema(state_schema=State), compile_options)
    app.add_agent(agent)

    business_registry = build_tool_registry(tools)
    for definition in business_registry.list_definitions():
        agent.tool_registry.register(
            definition,
            business_registry.get_handler(definition.name),
        )

    react_subgraph = StrategyFactory.create_as_node(
        StrategyType.REACT,
        llm_config=config,
        tool_registry=agent.tool_registry,
    )
    agent.add_node(react_subgraph)
    agent.add_edge(START_NODE, react_subgraph.name)
    agent.add_edge(react_subgraph.name, END_NODE)
    agent.compile()
    return agent


def _get_pending_interrupt(agent: Agent, session_id: str) -> dict | None:
    """从 checkpoint 读取挂起的 interrupt payload。"""
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


def _collect_hitl_response(request: dict) -> dict:
    """按 HITLSubgraph interrupt payload 交互收集 resume 值。"""
    hitl_type = request.get("type")
    payload = request.get("payload", {})
    print(f"\n[HITL] {request.get('description', 'Human input required')}")
    print(f"[HITL] payload={payload}")

    if hitl_type == "input":
        fields = payload.get("fields") or {}
        tool_calls = payload.get("tool_calls") or []
        tool_name_by_id = {
            tc.get("tool_call_id"): tc.get("name") or tc.get("tool_call_id")
            for tc in tool_calls
            if tc.get("tool_call_id")
        }
        # 新协议：fields = {tool_call_id: [{name, description}, ...]}
        if isinstance(fields, dict):
            values: dict[str, Any] = {}
            for tool_call_id, call_fields in fields.items():
                tool_name = tool_name_by_id.get(tool_call_id) or tool_call_id
                print(f"  [{tool_name} / {tool_call_id}]")
                per_call: dict[str, Any] = {}
                for field in call_fields or []:
                    name = field["name"]
                    desc = field.get("description") or name
                    per_call[name] = input(f"    {name} ({desc}): ").strip()
                values[tool_call_id] = per_call
            return {"values": values}
        # 旧扁平 list 兜底
        flat_values: dict[str, Any] = {}
        for field in fields:
            name = field["name"]
            desc = field.get("description") or name
            flat_values[name] = input(f"  {name} ({desc}): ").strip()
        return {"values": flat_values}

    if hitl_type == "approval":
        approved = input("  approve? (y/n): ").strip().lower() == "y"
        return {"approved": approved}

    raise ValueError(f"unsupported HITL interrupt type: {hitl_type!r}")


async def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = await agent.ainvoke(session_id, UserInput(text=user_text))

        while True:
            request = _get_pending_interrupt(agent, session_id)
            if request is None:
                break
            try:
                resume_values = _collect_hitl_response(request)
            except ValueError as exc:
                print(f"[HITL] {exc}")
                break

            result = await agent.aresume(session_id, resume_values)

        print("\nAssistant:")
        print(getattr(result, "text", result) if not isinstance(result, dict) else result.get("response", result))
        state = agent.get_state(session_id)
        print(f"[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


async def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant: ", end="", flush=True)
        printed = ""
        stream = await agent.astream(session_id, UserInput(text=user_text))
        async for chunk in stream:
            text = getattr(chunk, "text", "") or ""
            delta = text[len(printed):] if text.startswith(printed) else text
            printed = text
            if delta:
                print(delta, end="", flush=True)

        while True:
            request = _get_pending_interrupt(agent, session_id)
            if request is None:
                break
            try:
                resume_values = _collect_hitl_response(request)
            except ValueError as exc:
                print(f"\n[HITL] {exc}")
                break

            print("\nAssistant: ", end="", flush=True)
            printed = ""
            stream = await agent.astream_resume(session_id, resume_values)
            async for chunk in stream:
                text = getattr(chunk, "text", "") or ""
                delta = text[len(printed):] if text.startswith(printed) else text
                printed = text
                if delta:
                    print(delta, end="", flush=True)

        state = agent.get_state(session_id)
        print(f"\n[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    session_id = "react_test_session"

    tool_set_name, tools = select_tool_set()
    schema_path = (
        Path(__file__).resolve().parent
        / "tools"
        / f"{tool_set_name}_tools_schema.json"
    )
    export_tool_json_schema(tools, schema_path)
    print(f"Exported tool schema -> {schema_path}")

    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    agent_name = (
        f"react_stream_{tool_set_name}"
        if mode == "1"
        else f"react_invoke_{tool_set_name}"
    )
    agent = build_react_agent(agent_name, config, tools)
    print(f"Using tool set: {tool_set_name} ({len(tools)} tools)")
    print(f"Approval-required tools: {sorted(APPROVAL_REQUIRED_TOOLS)}")

    if mode == "1":
        asyncio.run(chat_stream(agent, session_id))
    else:
        asyncio.run(chat_invoke(agent, session_id))
