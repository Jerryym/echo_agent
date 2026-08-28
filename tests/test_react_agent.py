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
        registry.register(
            ToolDefinition(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"],
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


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT INVOKE")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        result = agent.invoke(session_id, UserInput(text=user_text))
        print("\nAssistant:")
        print(getattr(result, "text", result))
        state = agent.get_state(session_id)
        print(f"[DEBUG] state values: {state.values}")
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT AGENT STREAM")
    print("==============================\n")

    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break

        print("\nAssistant: ", end="", flush=True)
        printed = ""
        for chunk in agent.stream(session_id, UserInput(text=user_text)):
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

    if mode == "1":
        chat_stream(agent, session_id)
    else:
        chat_invoke(agent, session_id)
