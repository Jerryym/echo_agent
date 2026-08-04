"""Adapter proto ↔ Pydantic 转换与 gRPC 接线冒烟测试。"""

from __future__ import annotations

import asyncio
import json
import math

from echo_agent.adapter import AgentRuntime
from echo_agent.adapter.convert import (
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
            host="127.0.0.1",
            port=0,
        )
        assert isinstance(runtime, AgentRuntime)
        assert addr.startswith("127.0.0.1:")
        port = int(addr.rsplit(":", 1)[-1])
        assert port > 0
        await server.stop(grace=None)

    asyncio.run(_run())
