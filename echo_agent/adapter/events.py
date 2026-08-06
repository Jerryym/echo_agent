"""LangGraph messages 流 → Adapter AgentEvent 最小映射。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Iterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from echo_agent import Agent

from .schema import AgentEvent, AgentInvokeResult


def extract_output(result: Any) -> str:
    if result is None:
        return ""
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
    if pending is not None:
        return AgentInvokeResult(
            output=extract_output(result),
            interrupted=True,
            interrupt_payload=pending,
        )
    return AgentInvokeResult(output=extract_output(result), interrupted=False)


def _message_content(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content) if content is not None else ""


def map_stream_chunk(chunk: Any) -> AgentEvent | None:
    """将 LangGraph messages 流 chunk 映射为 AgentEvent；无法识别则返回 None。"""
    message = _unwrap_message(chunk)
    if message is None:
        return None

    if isinstance(message, AIMessage):
        text = _message_content(message)
        if not text and not getattr(message, "tool_calls", None):
            return None
        data: dict[str, Any] = {"role": "assistant", "content": text}
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            data["tool_calls"] = tool_calls
        return AgentEvent(type="message", data=data)

    if isinstance(message, HumanMessage):
        return AgentEvent(
            type="message",
            data={"role": "user", "content": _message_content(message)},
        )

    if isinstance(message, ToolMessage):
        return AgentEvent(
            type="tool_result",
            data={
                "role": "tool",
                "content": _message_content(message),
                "tool_call_id": getattr(message, "tool_call_id", None),
                "name": getattr(message, "name", None),
            },
        )

    return AgentEvent(
        type="message",
        data={
            "role": getattr(message, "type", "unknown"),
            "content": _message_content(message),
        },
    )


def _unwrap_message(chunk: Any) -> BaseMessage | None:
    if isinstance(chunk, BaseMessage):
        return chunk
    if isinstance(chunk, tuple):
        # subgraphs=True: (namespace, (message, metadata)) 或 (message, metadata)
        if len(chunk) == 2:
            first, second = chunk
            if isinstance(second, tuple) and second:
                candidate = second[0]
                if isinstance(candidate, BaseMessage):
                    return candidate
            if isinstance(first, BaseMessage):
                return first
            if isinstance(second, BaseMessage):
                return second
        for item in chunk:
            found = _unwrap_message(item)
            if found is not None:
                return found
    return None


async def iter_agent_events(
    agent: Agent,
    session_id: str,
    stream: AsyncIterator[Any],
) -> AsyncIterator[AgentEvent]:
    """消费 astream / astream_resume，产出归一化事件，并以 interrupt/done/error 收尾。"""
    last_output = ""
    try:
        async for chunk in stream:
            event = map_stream_chunk(chunk)
            if event is None:
                continue
            if event.type == "message" and event.data.get("role") == "assistant":
                content = event.data.get("content") or ""
                if content:
                    last_output = str(content)
            yield event

        # 中断事件
        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            yield AgentEvent(type="interrupt", data=pending)
            return

        if not last_output:
            state = agent.get_state(session_id)
            values = getattr(state, "values", None) or {}
            if isinstance(values, dict) and values.get("response"):
                last_output = str(values["response"])

        yield AgentEvent(type="done", data={"output": last_output})
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
    last_output = ""
    try:
        for chunk in stream:
            event = map_stream_chunk(chunk)
            if event is None:
                continue
            if event.type == "message" and event.data.get("role") == "assistant":
                content = event.data.get("content") or ""
                if content:
                    last_output = str(content)
            yield event

        # 中断事件
        pending = get_pending_interrupt(agent, session_id)
        if pending is not None:
            yield AgentEvent(type="interrupt", data=pending)
            return

        if not last_output:
            state = agent.get_state(session_id)
            values = getattr(state, "values", None) or {}
            if isinstance(values, dict) and values.get("response"):
                last_output = str(values["response"])

        yield AgentEvent(type="done", data={"output": last_output})
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent(
            type="error",
            data={"message": str(exc), "type": type(exc).__name__},
        )
        raise
