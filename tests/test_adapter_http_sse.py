"""HTTP Adapter SSE（Stream / StreamResume）测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from echo_agent.adapter.agent_runtime import AgentRuntime
from echo_agent.adapter.http.app import create_app
from echo_agent.adapter.http.sse import format_sse
from echo_agent.adapter.schema import AgentEvent
from echo_agent.core.model.input import UserInput


def _parse_sse(text: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    blocks = text.strip().split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        raw = "\n".join(data_lines)
        payload = json.loads(raw) if raw else {}
        events.append((event_type, payload))
    return events


def _client_with_runtime(runtime: AgentRuntime) -> TestClient:
    return TestClient(create_app(runtime))


def test_format_sse_roundtrip_shape():
    frame = format_sse(AgentEvent(type="message", data={"content": "hi"}))
    assert frame.startswith("event: message\n")
    assert 'data: {"content": "hi"}' in frame
    assert frame.endswith("\n\n")


def test_stream_happy_path_message_then_done():
    async def _gen() -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="message", data={"role": "assistant", "content": "hi"})
        yield AgentEvent(type="done", data={"output": "hi"})

    runtime = MagicMock(spec=AgentRuntime)
    runtime.get_agent = MagicMock(return_value=object())
    runtime.stream = MagicMock(return_value=_gen())
    runtime.cancel = AsyncMock(return_value=True)

    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/stream",
        json={"input": {"text": "hello"}, "metadata": {"trace_id": "t1"}},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    assert events == [
        ("message", {"role": "assistant", "content": "hi"}),
        ("done", {"output": "hi"}),
    ]
    args, kwargs = runtime.stream.call_args
    assert args[0] == "aid"
    assert args[1] == "sid"
    assert isinstance(args[2], UserInput)
    assert kwargs["metadata"] == {"trace_id": "t1"}


def test_stream_error_event_ends_stream_scheme_b():
    async def _gen() -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="message", data={"content": "partial"})
        yield AgentEvent(
            type="error",
            data={"type": "RuntimeError", "message": "boom"},
        )
        yield AgentEvent(type="done", data={"output": "should-not-appear"})

    runtime = MagicMock(spec=AgentRuntime)
    runtime.get_agent = MagicMock(return_value=object())
    runtime.stream = MagicMock(return_value=_gen())
    runtime.cancel = AsyncMock(return_value=True)

    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/stream",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert [e[0] for e in events] == ["message", "error"]
    assert events[-1][1]["message"] == "boom"


def test_stream_unknown_agent_maps_404_before_sse():
    runtime = MagicMock(spec=AgentRuntime)
    runtime.get_agent = MagicMock(side_effect=KeyError("agent not found: missing"))
    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/missing/sessions/sid/stream",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 404
    assert "agent not found" in resp.json()["detail"]


def test_stream_resume_happy_path():
    async def _gen() -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="done", data={"output": "ok"})

    runtime = MagicMock(spec=AgentRuntime)
    runtime.get_agent = MagicMock(return_value=object())
    runtime.stream_resume = MagicMock(return_value=_gen())
    runtime.cancel = AsyncMock(return_value=True)

    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/resume/stream",
        json={"values": {"approved": True}},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events == [("done", {"output": "ok"})]
    args, kwargs = runtime.stream_resume.call_args
    assert args[0] == "aid"
    assert args[1] == "sid"
    assert args[2] == {"approved": True}


def test_stream_cancelled_error_emits_cancelled_event():
    async def _gen() -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="message", data={"content": "x"})
        raise asyncio.CancelledError()

    runtime = MagicMock(spec=AgentRuntime)
    runtime.get_agent = MagicMock(return_value=object())
    runtime.stream = MagicMock(return_value=_gen())
    runtime.cancel = AsyncMock(return_value=True)

    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/stream",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[0][0] == "message"
    assert events[-1] == ("cancelled", {})
    runtime.cancel.assert_awaited()
