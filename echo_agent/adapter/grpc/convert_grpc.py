"""gRPC protobuf ↔ core 模型（经 adapter.convert 协议无关层）。"""

from __future__ import annotations

from typing import Any

from echo_agent.common.network import HttpRequest
from echo_agent.core.agent.agent_config import AgentConfig
from echo_agent.core.llm.llm_config import LLMConfig
from echo_agent.core.mcp.schema import MCPConnectionConfig
from echo_agent.core.model.input import Attachment, UserInput

from ..convert import (
    agent_config_from_fields,
    attachment_from_fields,
    coalesce_mcp_allowed_directories,
    encode_event_data,
    encode_interrupt_json,
    encode_json_object,
    llm_config_from_fields,
    mcp_connection_from_fields,
    runtime_options_from_fields,
    user_input_from_fields,
)
from ..schema import RuntimeOptions
from .pb import echo_agent_pb2 as pb


def http_request_from_proto(msg: pb.HttpRequest | None) -> HttpRequest | None:
    if msg is None:
        return None
    url = (msg.url or "").strip() or None
    headers = dict(msg.headers) if msg.headers else {}
    return HttpRequest(url=url, headers=headers)


def runtime_options_from_proto(msg: pb.RuntimeOptions | None) -> RuntimeOptions | None:
    if msg is None:
        return None
    return runtime_options_from_fields(
        checkpointer_kind=msg.checkpointer_kind or "",
        checkpointer_uri=msg.checkpointer_uri or "",
    )


def llm_config_from_proto(msg: pb.LLMConfig) -> LLMConfig:
    temperature: float | None = None
    if msg.HasField("temperature"):
        temperature = float(msg.temperature)
    return llm_config_from_fields(
        base_url=msg.base_url,
        api_key=msg.api_key,
        model_name=msg.model_name,
        model_provider=msg.model_provider or "",
        temperature=temperature,
        max_tokens=int(msg.max_tokens),
        timeout=int(msg.timeout),
        max_retries=int(msg.max_retries),
        use_responses_api=bool(msg.use_responses_api),
        output_version=msg.output_version or "",
        extra_json=msg.extra_json or "",
    )


def mcp_connection_from_proto(msg: pb.MCPConnectionConfig) -> MCPConnectionConfig:
    return mcp_connection_from_fields(
        name=msg.name,
        type=msg.type or "stdio",
        command=msg.command or None,
        args=list(msg.args) or None,
        url=msg.url or None,
        headers=dict(msg.headers) or None,
    )


def agent_config_from_proto(msg: pb.AgentConfig) -> AgentConfig:
    if not msg.HasField("llm_config"):
        raise ValueError("agent config llm_config is required")
    return agent_config_from_fields(
        name=msg.name,
        description=msg.description or None,
        llm_config=llm_config_from_proto(msg.llm_config),
        system_prompt=msg.system_prompt or None,
        mode=list(msg.mode),
        kb_list=list(msg.kb_list),
        skill_list=dict(msg.skill_list),
        mcp_allowed_directories=coalesce_mcp_allowed_directories(
            list(msg.mcp_allowed_directories)
        ),
        mcp_servers=[mcp_connection_from_proto(s) for s in msg.mcp_servers],
    )


def attachment_from_proto(msg: pb.Attachment) -> Attachment:
    return attachment_from_fields(type=msg.type or "", data=msg.data)


def user_input_from_proto(msg: pb.UserInput) -> UserInput:
    return user_input_from_fields(
        text=msg.text or "",
        attachments=[attachment_from_proto(a) for a in msg.attachments],
    )


def agent_response_to_proto(
    *,
    output: str,
    interrupted: bool,
    interrupt_payload: dict[str, Any] | None,
    agent_result: dict[str, Any] | None = None,
) -> pb.AgentResponse:
    return pb.AgentResponse(
        output=output or "",
        interrupted=interrupted,
        interrupt_json=encode_interrupt_json(interrupted, interrupt_payload),
        agent_result_json=encode_json_object(agent_result),
    )


def agent_event_to_proto(event_type: str, data: dict[str, Any] | Any) -> pb.AgentEvent:
    return pb.AgentEvent(type=event_type, data=encode_event_data(data))
