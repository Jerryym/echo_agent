"""
ReAct + 内置 read_file / write_file（真实 LLM 交互）

运行（需 tests/.env）：
  uv run python tests/test_react_agent_file.py

案例见 tests/docs/ReAct Agent File 测试案例文档.md
"""

from __future__ import annotations

import warnings
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver

from echo_agent import Agent, AgentConfig, BaseState, LLMConfig, UserInput
from echo_agent.core.app import Application
from echo_agent.core.graph import END_NODE, START_NODE, GraphCompileOptions, GraphSchema
from echo_agent.core.strategy import StrategyFactory, StrategyType
from echo_agent.core.tool import ToolRegistry
from env_config import build_config

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = Path(__file__).resolve().parent / "fixtures" / "files"
NOTE_NAME = "note.txt"
NOTE_CONTENT = "echo-file-tool-ok"


class State(BaseState):
    pass


def _ensure_sandbox() -> Path:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    note = SANDBOX / NOTE_NAME
    if not note.exists():
        note.write_text(NOTE_CONTENT, encoding="utf-8")
    return SANDBOX.resolve()


def build_react_file_agent(
    name: str, config: LLMConfig
) -> tuple[Agent, ToolRegistry, Path]:
    sandbox = _ensure_sandbox()
    Application._instance = None
    app = Application()

    agent_config = AgentConfig(
        name=name,
        description=name,
        llm_config=config,
        system_prompt=(
            "You can read and write files with read_file and write_file. "
            f"Only paths under {sandbox} are allowed. "
            "Prefer these tools for any file task. "
            "Do not claim success without calling the tool."
        ),
        allowed_directories=[str(sandbox)],
        skill_list=[],
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
    return agent, agent.tool_registry, sandbox


def _print_result(result) -> None:
    text = getattr(result, "text", None)
    print(text if text else result)


def chat_invoke(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT + FILE INVOKE")
    print("==============================\n")
    while True:
        user_text = input("You: ")
        if user_text.lower() in ["exit", "quit"]:
            break
        result = agent.invoke(session_id, UserInput(text=user_text))
        print("\nAssistant:")
        _print_result(result)
        print(f"[DEBUG] state values: {agent.get_state(session_id).values}")
        print("\n------------------------------\n")


def chat_stream(agent: Agent, session_id: str) -> None:
    print("\n==============================")
    print("TEST: REACT + FILE STREAM")
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
        print(f"\n[DEBUG] state values: {agent.get_state(session_id).values}")
        print("\n------------------------------\n")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")
    config = build_config()
    mode = input("Choose mode (invoke=0 / stream=1): ").strip()
    agent, registry, sandbox = build_react_file_agent("react_file_chat", config)
    note = sandbox / NOTE_NAME
    print("Tools:", [d.name for d in registry.list_definitions()])
    print("allowed_directories:", agent._agent_config.allowed_directories)
    print("sandbox:", sandbox)
    print("hint cases:")
    print(f"  1 read : 请用 read_file 读取 {note} ，原样复述全文")
    print(f"  2 write: 请用 write_file 把 hello-echo 写入 {sandbox / 'out.txt'}")
    print(f"  3 chain: 先读 {note} ，再把全文写入 {sandbox / 'copy.txt'}")
    print(f"  4 deny : 请读取 {REPO_ROOT / 'README.md'}")
    session_id = "react_file_session"
    if mode == "1":
        chat_stream(agent, session_id)
    else:
        chat_invoke(agent, session_id)
