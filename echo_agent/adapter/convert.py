"""协议无关的配置/输入转换（字段/DTO → core 模型）。

本模块不得依赖 gRPC / protobuf；协议绑定见 ``adapter.grpc.convert_grpc``。
"""

from __future__ import annotations

import json
from typing import Any

from echo_agent.core.agent.agent_config import AgentConfig
from echo_agent.core.llm.llm_config import LLMConfig
from echo_agent.core.mcp.schema import MCPConnectionConfig
from echo_agent.core.model.agent import AgentMode
from echo_agent.core.model.input import Attachment, UserInput

from .schema import RuntimeOptions


def runtime_options_from_fields(
    *,
    checkpointer_kind: str = "",
    checkpointer_uri: str = "",
) -> RuntimeOptions | None:
    kind = (checkpointer_kind or "").strip()
    uri = (checkpointer_uri or "").strip()
    if not kind and not uri:
        return None
    return RuntimeOptions(
        checkpointer_kind=kind or "memory",
        checkpointer_uri=uri or None,
    )


def parse_llm_extra_json(extra_json: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """解析 llm_config.extra_json → (extra_body, builtin_tools)。非法 JSON → ValueError。"""
    if not extra_json:
        return {}, []
    try:
        payload = json.loads(extra_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"llm_config.extra_json is not valid JSON: {exc}") from exc
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
    return extra_body, builtin_tools


def llm_config_from_fields(
    *,
    base_url: str,
    api_key: str,
    model_name: str,
    model_provider: str = "",
    temperature: float | None = None,
    max_tokens: int = 0,
    timeout: int = 0,
    max_retries: int = 0,
    use_responses_api: bool = False,
    output_version: str = "",
    extra_json: str = "",
) -> LLMConfig:
    """
    由普通字段构建 LLMConfig。

    ``temperature is None`` 表示未设置（回退默认 0.2）；
    ``max_tokens`` / ``timeout`` / ``max_retries`` 以 ``> 0`` 表示已设置。
    """
    if not base_url or not api_key or not model_name:
        raise ValueError("llm_config requires base_url, api_key, model_name")

    extra_body, builtin_tools = parse_llm_extra_json(extra_json)
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model_name,
        "model_provider": model_provider or "openai",
        "use_responses_api": bool(use_responses_api),
        "builtin_tools": builtin_tools,
        "extra_body": extra_body,
    }
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if max_tokens > 0:
        kwargs["max_tokens"] = int(max_tokens)
    if timeout > 0:
        kwargs["timeout"] = int(timeout)
    if max_retries > 0:
        kwargs["max_retries"] = int(max_retries)
    if output_version:
        kwargs["output_version"] = output_version

    return LLMConfig(**kwargs)


def mcp_connection_from_fields(
    *,
    name: str,
    type: str = "stdio",
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    headers: dict[str, str] | None = None,
) -> MCPConnectionConfig:
    mcp_type = (type or "stdio").strip() or "stdio"
    if mcp_type not in ("stdio", "http"):
        raise ValueError(f"unsupported mcp type: {mcp_type!r}")
    return MCPConnectionConfig(
        name=name,
        type=mcp_type,  # type: ignore[arg-type]
        command=command or None,
        args=list(args) if args else None,
        url=url or None,
        headers=dict(headers) if headers else None,
    )


def coalesce_mcp_allowed_directories(
    directories: list[str],
) -> str | list[str] | None:
    if not directories:
        return None
    if len(directories) == 1:
        return directories[0]
    return directories


def parse_agent_mode(value: str | AgentMode | None = None) -> AgentMode:
    """解析 ask/agent；空值回退 AGENT。"""
    if value is None:
        return AgentMode.AGENT
    if isinstance(value, AgentMode):
        return value
    raw = str(value).strip().lower()
    if not raw:
        return AgentMode.AGENT
    try:
        return AgentMode(raw)
    except ValueError as exc:
        raise ValueError(f"unsupported agent_mode: {value!r}") from exc


def parse_agent_modes(values: list[str] | list[AgentMode] | None) -> list[AgentMode] | None:
    """解析 AgentConfig.mode；空列表表示使用 Python 默认。"""
    if not values:
        return None
    return [parse_agent_mode(item) for item in values]


def agent_config_from_fields(
    *,
    name: str,
    llm_config: LLMConfig,
    description: str | None = None,
    system_prompt: str | None = None,
    mode: list[str] | list[AgentMode] | None = None,
    kb_list: list[str] | None = None,
    skill_list: dict[str, str] | None = None,
    mcp_allowed_directories: str | list[str] | None = None,
    mcp_servers: list[MCPConnectionConfig] | None = None,
) -> AgentConfig:
    if not name:
        raise ValueError("agent config name is required")
    kwargs: dict[str, Any] = {
        "name": name,
        "description": description or None,
        "llm_config": llm_config,
        "system_prompt": system_prompt or None,
        "kb_list": list(kb_list or []),
        "skill_list": dict(skill_list or {}),
        "mcp_allowed_directories": mcp_allowed_directories,
        "mcp_servers": list(mcp_servers or []),
        # 内置 Fetch / Filesystem 默认关闭；需启用时在 Python AgentConfig 显式打开
    }
    parsed_mode = parse_agent_modes(mode)
    if parsed_mode is not None:
        kwargs["mode"] = parsed_mode
    return AgentConfig(**kwargs)


def attachment_from_fields(*, type: str, format: str, data: str) -> Attachment:
    att_type = (type or "").strip()
    if att_type not in ("image", "audio", "file"):
        raise ValueError(f"unsupported attachment type: {att_type!r}")
    att_format = (format or "").strip()
    if att_format not in ("base64", "url"):
        raise ValueError(f"unsupported attachment format: {att_format!r}")
    return Attachment(type=att_type, format=att_format, data=data)


def user_input_from_fields(
    *,
    text: str = "",
    attachments: list[Attachment] | None = None,
) -> UserInput:
    return UserInput(
        text=text or "",
        attachments=list(attachments or []),
    )


def encode_interrupt_json(
    interrupted: bool,
    interrupt_payload: dict[str, Any] | None,
) -> str:
    if interrupted and interrupt_payload is not None:
        return json.dumps(interrupt_payload, ensure_ascii=False, default=str)
    return ""


def encode_json_object(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False, default=str)


def encode_event_data(data: dict[str, Any] | Any) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    return json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
