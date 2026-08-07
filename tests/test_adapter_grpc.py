"""Adapter proto ↔ Pydantic 转换与 gRPC 接线冒烟测试。"""

from __future__ import annotations

import asyncio
import json
import math

from echo_agent.adapter import AgentRuntime
from echo_agent.adapter.grpc.convert_grpc import (
    agent_config_from_proto,
    agent_event_to_proto,
    agent_response_to_proto,
    runtime_options_from_proto,
    user_input_from_proto,
)
from echo_agent.adapter.grpc.pb import echo_agent_pb2 as pb
from echo_agent.adapter.grpc.server import create_server


def test_agent_config_from_proto_basic():
    msg = pb.AgentConfig(
        name="demo",
        description="d",
        system_prompt="be helpful",
        llm_config=pb.LLMConfig(
            base_url="http://localhost/v1",
            api_key="sk-test",
            model_name="gpt-test",
            model_provider="openai",
            temperature=0.3,
            max_tokens=256,
            timeout=60,
            max_retries=2,
            extra_json=json.dumps(
                {
                    "extra_body": {"enable_thinking": True},
                    "builtin_tools": [{"type": "web_search"}],
                }
            ),
        ),
        kb_list=[],
        skill_list={"pdf": "/tmp/pdf"},
        mcp_allowed_directories=["/tmp"],
        mcp_servers=[
            pb.MCPConnectionConfig(
                name="remote",
                type="http",
                url="http://localhost:8000/mcp",
                headers={"Authorization": "Bearer x"},
            )
        ],
    )
    config = agent_config_from_proto(msg)
    assert config.name == "demo"
    assert config.description == "d"
    assert config.system_prompt == "be helpful"
    assert math.isclose(config.llm_config.temperature, 0.3, rel_tol=1e-9)
    assert config.llm_config.max_tokens == 256
    assert config.llm_config.extra_body == {"enable_thinking": True}
    assert config.llm_config.builtin_tools == [{"type": "web_search"}]
    assert config.skill_list == {"pdf": "/tmp/pdf"}
    assert config.mcp_allowed_directories == "/tmp"
    remote = next(s for s in config.mcp_servers if s.name == "remote")
    assert remote.type == "http"
    assert remote.url == "http://localhost:8000/mcp"


def test_agent_config_builtin_mcp_off_by_default():
    msg = pb.AgentConfig(
        name="demo",
        llm_config=pb.LLMConfig(
            base_url="http://x",
            api_key="k",
            model_name="m",
        ),
    )
    config = agent_config_from_proto(msg)
    assert config.enable_builtin_fetch is False
    assert config.enable_builtin_filesystem is False
    assert config.mcp_servers == []
    assert config.mcp_allowed_directories is None
    assert math.isclose(config.llm_config.temperature, 0.2, rel_tol=1e-9)


def test_llm_config_temperature_zero_is_honored():
    msg = pb.AgentConfig(
        name="demo",
        llm_config=pb.LLMConfig(
            base_url="http://x",
            api_key="k",
            model_name="m",
            temperature=0.0,
            max_tokens=0,
            timeout=0,
            max_retries=0,
        ),
    )
    assert msg.llm_config.HasField("temperature")
    config = agent_config_from_proto(msg)
    assert config.llm_config.temperature == 0.0
    # 其余标量 0 = 未设置 → Python 默认
    assert config.llm_config.max_tokens == 1024
    assert config.llm_config.timeout == 1200
    assert config.llm_config.max_retries == 3


def test_llm_config_invalid_extra_json_raises_value_error():
    from echo_agent.adapter.grpc.convert_grpc import llm_config_from_proto

    msg = pb.LLMConfig(
        base_url="http://x",
        api_key="k",
        model_name="m",
        extra_json="{",
    )
    try:
        llm_config_from_proto(msg)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "extra_json" in str(exc)
        assert not isinstance(exc, json.JSONDecodeError)


def test_llm_config_extra_json_must_be_object():
    from echo_agent.adapter.grpc.convert_grpc import llm_config_from_proto

    msg = pb.LLMConfig(
        base_url="http://x",
        api_key="k",
        model_name="m",
        extra_json="[]",
    )
    try:
        llm_config_from_proto(msg)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "JSON object" in str(exc)


def test_servicer_parse_resume_invalid_values_json_raises_value_error():
    from echo_agent.adapter.grpc.service import EchoAgentServicer

    req = pb.ResumeRequest(
        agent_id="aid",
        session_id="sid",
        values_json="{",
    )
    try:
        EchoAgentServicer._parse_resume(req)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "values_json" in str(exc)


def test_user_input_and_response_events():
    user = user_input_from_proto(
        pb.UserInput(
            text="hello",
            attachments=[pb.Attachment(type="file", data="https://x/a.pdf")],
        )
    )
    assert user.text == "hello"
    assert user.attachments[0].type == "file"

    resp = agent_response_to_proto(
        output="ok",
        interrupted=True,
        interrupt_payload={"type": "approval", "description": "确认？"},
    )
    assert resp.interrupted is True
    assert json.loads(resp.interrupt_json)["type"] == "approval"

    event = agent_event_to_proto("message", {"role": "assistant", "content": "hi"})
    assert event.type == "message"
    assert json.loads(event.data.decode("utf-8"))["content"] == "hi"


def test_runtime_options_from_proto():
    assert runtime_options_from_proto(None) is None
    assert runtime_options_from_proto(pb.RuntimeOptions()) is None
    opts = runtime_options_from_proto(pb.RuntimeOptions(checkpointer_kind="memory"))
    assert opts is not None
    assert opts.checkpointer_kind == "memory"


async def _stub_factory(config, runtime_options=None):
    raise RuntimeError("stub factory should not be called in bind test")


def test_create_server_binds():
    async def _run():
        server, runtime, addr = await create_server(
            AgentRuntime(factory=_stub_factory),
            port=0,
        )
        assert isinstance(runtime, AgentRuntime)
        assert addr.startswith("127.0.0.1:")
        port = int(addr.rsplit(":", 1)[-1])
        assert port > 0
        await server.stop(grace=None)

    asyncio.run(_run())


def test_servicer_parse_invoke_metadata():
    from echo_agent.adapter.grpc.service import EchoAgentServicer

    req = pb.InvokeRequest(
        agent_id="aid",
        session_id="sid",
        input=pb.UserInput(text="hi"),
        metadata={
            "trace_id": "t1",
            "http_headers": json.dumps({"Authorization": "Bearer x"}),
        },
    )
    agent_id, session_id, user_input, metadata = EchoAgentServicer._parse_invoke(req)
    assert agent_id == "aid"
    assert session_id == "sid"
    assert user_input.text == "hi"
    assert metadata == {
        "trace_id": "t1",
        "http_headers": json.dumps({"Authorization": "Bearer x"}),
    }

    empty = pb.InvokeRequest(
        agent_id="aid",
        session_id="sid",
        input=pb.UserInput(text="hi"),
    )
    *_, metadata_empty = EchoAgentServicer._parse_invoke(empty)
    assert metadata_empty is None


def test_servicer_parse_resume_metadata():
    from echo_agent.adapter.grpc.service import EchoAgentServicer

    req = pb.ResumeRequest(
        agent_id="aid",
        session_id="sid",
        values_json=json.dumps({"approved": True}),
        metadata={"trace_id": "t2"},
    )
    agent_id, session_id, values, metadata = EchoAgentServicer._parse_resume(req)
    assert agent_id == "aid"
    assert session_id == "sid"
    assert values == {"approved": True}
    assert metadata == {"trace_id": "t2"}


def test_agent_normalize_metadata_http_headers_scheme_b():
    from echo_agent.core.agent.agent import Agent
    from echo_agent.core.agent.runnable_metadata import METADATA_HTTP_HEADERS_KEY

    agent = object.__new__(Agent)
    normalized = agent._normalize_invoke_metadata(
        {
            "trace_id": "t1",
            METADATA_HTTP_HEADERS_KEY: json.dumps({"Authorization": "Bearer x"}),
        }
    )
    assert normalized["trace_id"] == "t1"
    assert normalized[METADATA_HTTP_HEADERS_KEY] == {"Authorization": "Bearer x"}

    # already a dict
    normalized2 = agent._normalize_invoke_metadata(
        {METADATA_HTTP_HEADERS_KEY: {"X-Request-Id": "1"}}
    )
    assert normalized2[METADATA_HTTP_HEADERS_KEY] == {"X-Request-Id": "1"}

    try:
        agent._normalize_invoke_metadata({METADATA_HTTP_HEADERS_KEY: "{"})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "http_headers" in str(exc)


def test_agent_build_runnable_config_puts_metadata():
    from echo_agent.core.agent.agent import Agent
    from echo_agent.core.agent.runnable_metadata import METADATA_HTTP_HEADERS_KEY

    agent = object.__new__(Agent)
    cfg = agent._build_runnable_config(
        "sess-1",
        {
            "trace_id": "t1",
            METADATA_HTTP_HEADERS_KEY: json.dumps({"Authorization": "Bearer x"}),
        },
    )
    assert cfg["configurable"]["thread_id"] == "sess-1"
    meta = cfg["configurable"]["metadata"]
    assert meta["trace_id"] == "t1"
    assert meta[METADATA_HTTP_HEADERS_KEY] == {"Authorization": "Bearer x"}


def test_agent_runtime_forwards_metadata():
    from echo_agent.core.model.input import UserInput

    captured: dict = {}

    class _FakeAgent:
        async def ainvoke(self, session_id, input, metadata=None):
            captured["session_id"] = session_id
            captured["input"] = input
            captured["metadata"] = metadata
            return {"response": "ok"}

        def get_state(self, session_id):
            class _State:
                interrupts = ()
                tasks = ()

            return _State()

    async def _factory(config, runtime_options=None):
        return _FakeAgent()

    async def _run():
        # bypass Agent type check in create_agent by injecting map
        runtime = AgentRuntime(factory=_factory)
        fake = _FakeAgent()
        runtime._agent_map["aid"] = fake  # type: ignore[assignment]
        result = await runtime.invoke(
            "aid",
            "sid",
            UserInput(text="hi"),
            metadata={"trace_id": "t1"},
        )
        assert captured["session_id"] == "sid"
        assert captured["metadata"] == {"trace_id": "t1"}
        assert result.output == "ok"
        assert result.interrupted is False

    asyncio.run(_run())


def test_iter_agent_events_yields_error_then_reraises():
    from echo_agent.adapter.events import iter_agent_events

    class _Agent:
        def get_state(self, session_id):
            raise AssertionError("should not reach done path")

    async def _failing_stream():
        yield ("ignored",)  # map_stream_chunk returns None
        raise RuntimeError("boom")

    async def _run():
        events = []
        raised = None
        try:
            async for event in iter_agent_events(_Agent(), "sid", _failing_stream()):
                events.append(event)
        except RuntimeError as exc:
            raised = exc
        assert raised is not None
        assert str(raised) == "boom"
        assert len(events) == 1
        assert events[0].type == "error"
        assert events[0].data["type"] == "RuntimeError"
        assert events[0].data["message"] == "boom"

    asyncio.run(_run())


def test_iter_agent_events_sync_yields_error_then_reraises():
    from echo_agent.adapter.events import iter_agent_events_sync

    class _Agent:
        def get_state(self, session_id):
            raise AssertionError("should not reach done path")

    def _failing_stream():
        yield ("ignored",)
        raise ValueError("bad")

    events = []
    raised = None
    try:
        for event in iter_agent_events_sync(_Agent(), "sid", _failing_stream()):
            events.append(event)
    except ValueError as exc:
        raised = exc
    assert raised is not None
    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].data["message"] == "bad"


def test_internal_message_is_short():
    from echo_agent.adapter.grpc.service import _internal_message

    assert _internal_message("Invoke") == "Invoke failed"
    assert _internal_message("CreateAgent") == "CreateAgent failed"


def test_delete_agent_and_max_agents():
    from echo_agent.adapter.agent_runtime import AgentLimitExceededError, AgentRuntime

    class _FakeAgent:
        pass

    async def _factory(config, runtime_options=None):
        return _FakeAgent()

    async def _run():
        runtime = AgentRuntime(factory=_factory, max_agents=1)
        runtime._agent_map["a1"] = _FakeAgent()  # type: ignore[assignment]
        try:
            await runtime.create_agent(config=None)  # type: ignore[arg-type]
            raise AssertionError("expected AgentLimitExceededError")
        except AgentLimitExceededError:
            pass

        await runtime.delete_agent("a1")
        try:
            runtime.get_agent("a1")
            raise AssertionError("expected KeyError")
        except KeyError:
            pass

        # empty id
        try:
            await runtime.delete_agent("  ")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    asyncio.run(_run())
