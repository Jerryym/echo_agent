"""AgentResult 流 → Adapter AgentEvent 映射。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator

from echo_agent import Agent
from echo_agent.core.model.agent import AgentResult

from .schema import AgentEvent, AgentInvokeResult


def extract_output(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, AgentResult):
        return result.text or ""
    text = getattr(result, "text", None)
    if isinstance(text, str) and text:
        return text
    if isinstance(result, dict):
        response = result.get("response")
        if response is not None:
            return str(response)
        hitl_response = result.get("hitl_response")
        if hitl_response is not None:
            if hasattr(hitl_response, "model_dump"):
                return json.dumps(hitl_response.model_dump(), ensure_ascii=False, default=str)
            return str(hitl_response)
        return ""
    return str(result)


def get_pending_interrupt(agent: Agent, session_id: str) -> dict[str, Any] | None:
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
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {"value": value}


def to_invoke_result(agent: Agent, session_id: str, result: Any) -> AgentInvokeResult:
    pending = get_pending_interrupt(agent, session_id)
    snapshot = agent_result_event_data(result) if isinstance(result, AgentResult) else None
    if pending is not None:
        return AgentInvokeResult(
            output=extract_output(result),
            interrupted=True,
            interrupt_payload=pending,
            agent_result=snapshot,
        )
    return AgentInvokeResult(
        output=extract_output(result),
        interrupted=False,
        agent_result=snapshot,
    )


def agent_result_event_data(result: AgentResult) -> dict[str, Any]:
    """AgentResult → AgentEvent.data（稳定 JSON 形态）。"""
    usage = result.token_usage
    return {
        "text": result.text,
        "reasoning": list(result.reasoning),
        "token_usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        },
    }


def map_agent_result(result: AgentResult) -> AgentEvent:
    """将本轮 AgentResult 快照映射为流式事件。"""
    return AgentEvent(type="agent_result", data=agent_result_event_data(result))


def _as_agent_result(chunk: Any) -> AgentResult | None:
    if isinstance(chunk, AgentResult):
        return chunk
    return None


async def iter_agent_events(
    agent: Agent,
    session_id: str,
    stream: AsyncIterator[Any],
) -> AsyncIterator[AgentEvent]:
    """消费 astream / astream_resume 的 AgentResult，产出归一化事件并以 interrupt/done/error 收尾。"""
    last_result: AgentResult | None = None
    try:
        async for chunk in stream:
            result = _as_agent_result(chunk)
            if result is None:
                continue
            last_result = result
            yield map_agent_result(result)

        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            yield AgentEvent(type="interrupt", data=pending)
            return

        output = extract_output(last_result) if last_result is not None else ""
        if not output:
            state = agent.get_state(session_id)
            values = getattr(state, "values", None) or {}
            if isinstance(values, dict) and values.get("response"):
                output = str(values["response"])

        done_data: dict[str, Any] = {"output": output}
        if last_result is not None:
            done_data["agent_result"] = agent_result_event_data(last_result)
        yield AgentEvent(type="done", data=done_data)
    except Exception as exc:  # noqa: BLE001 — 先 error 事件，再抛出供上层 abort
        yield AgentEvent(
            type="error",
            data={"message": str(exc), "type": type(exc).__name__},
        )
        raise


def iter_agent_events_sync(
    agent: Agent,
    session_id: str,
    stream: Iterator[Any],
) -> Iterator[AgentEvent]:
    last_result: AgentResult | None = None
    try:
        for chunk in stream:
            result = _as_agent_result(chunk)
            if result is None:
                continue
            last_result = result
            yield map_agent_result(result)

        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            yield AgentEvent(type="interrupt", data=pending)
            return

        output = extract_output(last_result) if last_result is not None else ""
        if not output:
            state = agent.get_state(session_id)
            values = getattr(state, "values", None) or {}
            if isinstance(values, dict) and values.get("response"):
                output = str(values["response"])

        done_data: dict[str, Any] = {"output": output}
        if last_result is not None:
            done_data["agent_result"] = agent_result_event_data(last_result)
        yield AgentEvent(type="done", data=done_data)
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent(
            type="error",
            data={"message": str(exc), "type": type(exc).__name__},
        )
        raise
