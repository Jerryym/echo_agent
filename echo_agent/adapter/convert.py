"""AgentConfig / UserInput 等 proto ↔ Pydantic 转换。"""

from __future__ import annotations

import json
from typing import Any

from echo_agent.core.agent.agent_config import AgentConfig
from echo_agent.core.llm.llm_config import LLMConfig
from echo_agent.core.mcp.schema import MCPConnectionConfig
from echo_agent.core.model.input import Attachment, UserInput

from .grpc.pb import echo_agent_pb2 as pb
from .schema import RuntimeOptions


def runtime_options_from_proto(msg: pb.RuntimeOptions | None) -> RuntimeOptions | None:
    if msg is None:
        return None
    kind = (msg.checkpointer_kind or "").strip()
    uri = (msg.checkpointer_uri or "").strip()
    if not kind and not uri:
        return None
    return RuntimeOptions(
        checkpointer_kind=kind or "memory",
        checkpointer_uri=uri or None,
    )


def llm_config_from_proto(msg: pb.LLMConfig) -> LLMConfig:
    if not msg.base_url or not msg.api_key or not msg.model_name:
        raise ValueError("llm_config requires base_url, api_key, model_name")

    extra_body: dict[str, Any] = {}
    builtin_tools: list[dict[str, Any]] = []
    if msg.extra_json:
        payload = json.loads(msg.extra_json)
        if not isinstance(payload, dict):
            raise ValueError("llm_config.extra_json must be a JSON object")
        builtin_tools = list(payload.get("builtin_tools") or [])
        body = payload.get("extra_body")
        if isinstance(body, dict):
            extra_body = body
        else:
            extra_body = {
                k: v
                for k, v in payload.items()
                if k not in ("builtin_tools", "extra_body")
            }

    kwargs: dict[str, Any] = {
        "base_url": msg.base_url,
        "api_key": msg.api_key,
        "model_name": msg.model_name,
        "model_provider": msg.model_provider or "openai",
        "use_responses_api": bool(msg.use_responses_api),
        "builtin_tools": builtin_tools,
        "extra_body": extra_body,
    }
    # proto3 标量 0 / "" 无法区分未设置；对明显「未填」的字段回退 Python 默认值
    if msg.temperature != 0.0:
        kwargs["temperature"] = float(msg.temperature)
    if msg.max_tokens > 0:
        kwargs["max_tokens"] = int(msg.max_tokens)
    if msg.timeout > 0:
        kwargs["timeout"] = int(msg.timeout)
    if msg.max_retries > 0:
        kwargs["max_retries"] = int(msg.max_retries)
    if msg.output_version:
        kwargs["output_version"] = msg.output_version

    return LLMConfig(**kwargs)


def mcp_connection_from_proto(msg: pb.MCPConnectionConfig) -> MCPConnectionConfig:
    mcp_type = (msg.type or "stdio").strip() or "stdio"
    if mcp_type not in ("stdio", "http"):
        raise ValueError(f"unsupported mcp type: {mcp_type!r}")
    return MCPConnectionConfig(
        name=msg.name,
        type=mcp_type,  # type: ignore[arg-type]
        command=msg.command or None,
        args=list(msg.args) or None,
        url=msg.url or None,
        headers=dict(msg.headers) or None,
    )


def agent_config_from_proto(msg: pb.AgentConfig) -> AgentConfig:
    if not msg.name:
        raise ValueError("agent config name is required")
    if not msg.HasField("llm_config"):
        raise ValueError("agent config llm_config is required")
    directories = list(msg.mcp_allowed_directories)
    mcp_allowed_directories: str | list[str] | None
    if not directories:
        mcp_allowed_directories = None
    elif len(directories) == 1:
        mcp_allowed_directories = directories[0]
    else:
        mcp_allowed_directories = directories

    return AgentConfig(
        name=msg.name,
        description=msg.description or None,
        llm_config=llm_config_from_proto(msg.llm_config),
        system_prompt=msg.system_prompt or None,
        kb_list=list(msg.kb_list),
        skill_list=dict(msg.skill_list),
        mcp_allowed_directories=mcp_allowed_directories,
        mcp_servers=[mcp_connection_from_proto(s) for s in msg.mcp_servers],
        # 内置 Fetch / Filesystem 默认关闭；需启用时在 Python AgentConfig 显式打开
    )


def attachment_from_proto(msg: pb.Attachment) -> Attachment:
    att_type = (msg.type or "").strip()
    if att_type not in ("image", "audio", "file"):
        raise ValueError(f"unsupported attachment type: {att_type!r}")
    return Attachment(type=att_type, data=msg.data)  # type: ignore[arg-type]


def user_input_from_proto(msg: pb.UserInput) -> UserInput:
    return UserInput(
        text=msg.text or "",
        attachments=[attachment_from_proto(a) for a in msg.attachments],
    )


def agent_response_to_proto(
    *,
    output: str,
    interrupted: bool,
    interrupt_payload: dict[str, Any] | None,
) -> pb.AgentResponse:
    interrupt_json = ""
    if interrupted and interrupt_payload is not None:
        interrupt_json = json.dumps(interrupt_payload, ensure_ascii=False, default=str)
    return pb.AgentResponse(
        output=output or "",
        interrupted=interrupted,
        interrupt_json=interrupt_json,
    )


def agent_event_to_proto(event_type: str, data: dict[str, Any] | Any) -> pb.AgentEvent:
    if isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
    else:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    return pb.AgentEvent(type=event_type, data=payload)
