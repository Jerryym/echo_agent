"""HTTP Adapter 同步 API 测试（无 Stream/SSE）。"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from echo_agent.adapter import AgentLimitExceededError, AgentRuntime
from echo_agent.adapter.http.app import create_app
from echo_agent.adapter.http.errors import internal_message
from echo_agent.adapter.schema import AgentInvokeResult
from echo_agent.core.model.input import UserInput


def _minimal_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "name": "demo",
        "llm_config": {
            "base_url": "http://localhost/v1",
            "api_key": "sk-test",
            "model_name": "gpt-test",
        },
    }
    cfg.update(overrides)
    return cfg


def _client_with_runtime(runtime: AgentRuntime) -> TestClient:
    return TestClient(create_app(runtime))


def test_internal_message_is_short():
    assert internal_message("Invoke") == "Invoke failed"
    assert internal_message("CreateAgent") == "CreateAgent failed"


def test_create_invoke_resume_cancel_delete_happy_path():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.create_agent = AsyncMock(return_value="aid-1")
    runtime.delete_agent = AsyncMock()
    runtime.invoke = AsyncMock(
        return_value=AgentInvokeResult(output="hello", interrupted=False)
    )
    runtime.resume = AsyncMock(
        return_value=AgentInvokeResult(
            output="",
            interrupted=True,
            interrupt_payload={"type": "approval"},
        )
    )
    runtime.cancel = AsyncMock(return_value=True)

    client = _client_with_runtime(runtime)

    resp = client.post("/v1/agents", json={"config": _minimal_config()})
    assert resp.status_code == 200
    assert resp.json() == {"id": "aid-1"}
    runtime.create_agent.assert_awaited()

    resp = client.post(
        "/v1/agents/aid-1/sessions/sid-1/invoke",
        json={
            "input": {"text": "hi"},
            "metadata": {
                "trace_id": "t1",
                "http_headers": json.dumps({"Authorization": "Bearer x"}),
            },
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "output": "hello",
        "interrupted": False,
        "interrupt": None,
    }
    args, kwargs = runtime.invoke.await_args
    assert args[0] == "aid-1"
    assert args[1] == "sid-1"
    assert isinstance(args[2], UserInput)
    assert args[2].text == "hi"
    assert kwargs["metadata"]["trace_id"] == "t1"

    resp = client.post(
        "/v1/agents/aid-1/sessions/sid-1/resume",
        json={"values": {"approved": True}, "metadata": {"trace_id": "t2"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["interrupted"] is True
    assert body["interrupt"] == {"type": "approval"}

    resp = client.post("/v1/agents/aid-1/sessions/sid-1/cancel")
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}

    resp = client.delete("/v1/agents/aid-1")
    assert resp.status_code == 204
    runtime.delete_agent.assert_awaited_with("aid-1")


def test_create_agent_limit_exhausted_maps_429():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.create_agent = AsyncMock(
        side_effect=AgentLimitExceededError("max_agents limit reached: 1")
    )
    client = _client_with_runtime(runtime)
    resp = client.post("/v1/agents", json={"config": _minimal_config()})
    assert resp.status_code == 429
    assert "max_agents" in resp.json()["detail"]


def test_delete_unknown_agent_maps_404():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.delete_agent = AsyncMock(side_effect=KeyError("agent not found: missing"))
    client = _client_with_runtime(runtime)
    resp = client.delete("/v1/agents/missing")
    assert resp.status_code == 404
    assert "agent not found" in resp.json()["detail"]


def test_invoke_value_error_maps_400():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.invoke = AsyncMock(side_effect=ValueError("session_id is required"))
    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/invoke",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 400
    assert "session_id" in resp.json()["detail"]


def test_invoke_runtime_error_maps_409():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.invoke = AsyncMock(side_effect=RuntimeError("session already running: sid"))
    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/invoke",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 409


def test_invoke_internal_error_is_scrubbed():
    runtime = AsyncMock(spec=AgentRuntime)
    runtime.invoke = AsyncMock(side_effect=OSError("/secret/path boom"))
    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/invoke",
        json={"input": {"text": "x"}},
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Invoke failed"
    assert "/secret" not in resp.text


def test_resume_requires_values_field():
    runtime = AsyncMock(spec=AgentRuntime)
    client = _client_with_runtime(runtime)
    resp = client.post(
        "/v1/agents/aid/sessions/sid/resume",
        json={"metadata": {"a": "b"}},
    )
    assert resp.status_code == 400


def test_create_invalid_config_maps_400():
    runtime = AsyncMock(spec=AgentRuntime)
    client = _client_with_runtime(runtime)
    resp = client.post("/v1/agents", json={"config": {"name": "x"}})
    assert resp.status_code == 400
