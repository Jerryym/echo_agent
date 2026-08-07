"""HTTP 请求/响应模型（对齐 gRPC 契约语义；JSON 形态更自然）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from echo_agent.core.agent.agent_config import AgentConfig
from echo_agent.core.model.input import UserInput

from ..convert import runtime_options_from_fields
from ..schema import RuntimeOptions


class RuntimeOptionsBody(BaseModel):
    checkpointer_kind: str = ""
    checkpointer_uri: str | None = None

    def to_runtime_options(self) -> RuntimeOptions | None:
        return runtime_options_from_fields(
            checkpointer_kind=self.checkpointer_kind or "",
            checkpointer_uri=self.checkpointer_uri or "",
        )


class CreateAgentBody(BaseModel):
    config: AgentConfig
    runtime_options: RuntimeOptionsBody | None = None


class AgentHandleBody(BaseModel):
    id: str


class InvokeBody(BaseModel):
    input: UserInput
    # 与 proto map<string,string> 对齐；保留键 http_headers 值为 JSON object 字符串
    metadata: dict[str, str] | None = None


class ResumeBody(BaseModel):
    # 必填（可为空对象）；对齐 gRPC values_json 须为 JSON object
    values: dict[str, Any]
    metadata: dict[str, str] | None = None


class AgentResponseBody(BaseModel):
    output: str = ""
    interrupted: bool = False
    interrupt: dict[str, Any] | None = None


class CancelResponseBody(BaseModel):
    cancelled: bool
