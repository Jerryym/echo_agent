from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from echo_agent import Agent
from echo_agent.core.tool import ToolDefinition, ToolRegistry


def ensure_tests_tools_path() -> None:
    """将 tests/ 加入 path，便于复用 business_tools。"""
    tests_dir = Path(__file__).resolve().parents[2] / "tests"
    path = str(tests_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


def as_runnable_tool(tool_obj: Any) -> Any:
    if hasattr(tool_obj, "invoke"):
        return tool_obj
    return StructuredTool.from_function(tool_obj)


def build_tool_registry(
    tools: Sequence[Any],
    *,
    approval_required: set[str] | None = None,
) -> ToolRegistry:
    approval_required = approval_required or set()
    registry = ToolRegistry()
    for tool_obj in tools:
        runnable = as_runnable_tool(tool_obj)
        tool = convert_to_openai_tool(runnable)
        fn = tool["function"]
        name = fn["name"]
        registry.register(
            ToolDefinition(
                name=name,
                description=fn["description"],
                parameters=fn["parameters"],
                meta_data={
                    "required_approval": name in approval_required,
                },
            ),
            runnable,
        )
    return registry


def get_pending_interrupt(agent: Agent, session_id: str) -> dict | None:
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


def extract_reply(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        response = result.get("response")
        if response is not None:
            return str(response)
        hitl_response = result.get("hitl_response")
        if hitl_response is not None:
            if hasattr(hitl_response, "model_dump"):
                return str(hitl_response.model_dump())
            return str(hitl_response)
        return str(result)
    return str(result)
