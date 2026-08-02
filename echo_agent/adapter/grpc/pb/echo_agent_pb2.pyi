from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CreateAgentRequest(_message.Message):
    __slots__ = ("config", "runtime_options")
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    RUNTIME_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    config: AgentConfig
    runtime_options: RuntimeOptions
    def __init__(self, config: _Optional[_Union[AgentConfig, _Mapping]] = ..., runtime_options: _Optional[_Union[RuntimeOptions, _Mapping]] = ...) -> None: ...

class AgentHandle(_message.Message):
    __slots__ = ("id",)
    ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    def __init__(self, id: _Optional[str] = ...) -> None: ...

class RuntimeOptions(_message.Message):
    __slots__ = ("checkpointer_kind", "checkpointer_uri")
    CHECKPOINTER_KIND_FIELD_NUMBER: _ClassVar[int]
    CHECKPOINTER_URI_FIELD_NUMBER: _ClassVar[int]
    checkpointer_kind: str
    checkpointer_uri: str
    def __init__(self, checkpointer_kind: _Optional[str] = ..., checkpointer_uri: _Optional[str] = ...) -> None: ...

class AgentConfig(_message.Message):
    __slots__ = ("name", "description", "llm_config", "system_prompt", "kb_list", "skill_list", "mcp_allowed_directories", "mcp_servers")
    class SkillListEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    LLM_CONFIG_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    KB_LIST_FIELD_NUMBER: _ClassVar[int]
    SKILL_LIST_FIELD_NUMBER: _ClassVar[int]
    MCP_ALLOWED_DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    MCP_SERVERS_FIELD_NUMBER: _ClassVar[int]
    name: str
    description: str
    llm_config: LLMConfig
    system_prompt: str
    kb_list: _containers.RepeatedScalarFieldContainer[str]
    skill_list: _containers.ScalarMap[str, str]
    mcp_allowed_directories: _containers.RepeatedScalarFieldContainer[str]
    mcp_servers: _containers.RepeatedCompositeFieldContainer[MCPConnectionConfig]
    def __init__(self, name: _Optional[str] = ..., description: _Optional[str] = ..., llm_config: _Optional[_Union[LLMConfig, _Mapping]] = ..., system_prompt: _Optional[str] = ..., kb_list: _Optional[_Iterable[str]] = ..., skill_list: _Optional[_Mapping[str, str]] = ..., mcp_allowed_directories: _Optional[_Iterable[str]] = ..., mcp_servers: _Optional[_Iterable[_Union[MCPConnectionConfig, _Mapping]]] = ...) -> None: ...

class LLMConfig(_message.Message):
    __slots__ = ("base_url", "api_key", "model_name", "model_provider", "temperature", "max_tokens", "timeout", "max_retries", "use_responses_api", "output_version", "extra_json")
    BASE_URL_FIELD_NUMBER: _ClassVar[int]
    API_KEY_FIELD_NUMBER: _ClassVar[int]
    MODEL_NAME_FIELD_NUMBER: _ClassVar[int]
    MODEL_PROVIDER_FIELD_NUMBER: _ClassVar[int]
    TEMPERATURE_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TIMEOUT_FIELD_NUMBER: _ClassVar[int]
    MAX_RETRIES_FIELD_NUMBER: _ClassVar[int]
    USE_RESPONSES_API_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_VERSION_FIELD_NUMBER: _ClassVar[int]
    EXTRA_JSON_FIELD_NUMBER: _ClassVar[int]
    base_url: str
    api_key: str
    model_name: str
    model_provider: str
    temperature: float
    max_tokens: int
    timeout: int
    max_retries: int
    use_responses_api: bool
    output_version: str
    extra_json: str
    def __init__(self, base_url: _Optional[str] = ..., api_key: _Optional[str] = ..., model_name: _Optional[str] = ..., model_provider: _Optional[str] = ..., temperature: _Optional[float] = ..., max_tokens: _Optional[int] = ..., timeout: _Optional[int] = ..., max_retries: _Optional[int] = ..., use_responses_api: _Optional[bool] = ..., output_version: _Optional[str] = ..., extra_json: _Optional[str] = ...) -> None: ...

class MCPConnectionConfig(_message.Message):
    __slots__ = ("name", "type", "command", "args", "url", "headers")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    name: str
    type: str
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    url: str
    headers: _containers.ScalarMap[str, str]
    def __init__(self, name: _Optional[str] = ..., type: _Optional[str] = ..., command: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ...) -> None: ...

class UserInput(_message.Message):
    __slots__ = ("text", "attachments")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    text: str
    attachments: _containers.RepeatedCompositeFieldContainer[Attachment]
    def __init__(self, text: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[Attachment, _Mapping]]] = ...) -> None: ...

class Attachment(_message.Message):
    __slots__ = ("type", "data")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: str
    data: str
    def __init__(self, type: _Optional[str] = ..., data: _Optional[str] = ...) -> None: ...

class InvokeRequest(_message.Message):
    __slots__ = ("agent_id", "session_id", "input")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    INPUT_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    session_id: str
    input: UserInput
    def __init__(self, agent_id: _Optional[str] = ..., session_id: _Optional[str] = ..., input: _Optional[_Union[UserInput, _Mapping]] = ...) -> None: ...

class AgentResponse(_message.Message):
    __slots__ = ("output", "interrupted", "interrupt_json")
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    INTERRUPTED_FIELD_NUMBER: _ClassVar[int]
    INTERRUPT_JSON_FIELD_NUMBER: _ClassVar[int]
    output: str
    interrupted: bool
    interrupt_json: str
    def __init__(self, output: _Optional[str] = ..., interrupted: _Optional[bool] = ..., interrupt_json: _Optional[str] = ...) -> None: ...

class ResumeRequest(_message.Message):
    __slots__ = ("agent_id", "session_id", "values_json")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    VALUES_JSON_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    session_id: str
    values_json: str
    def __init__(self, agent_id: _Optional[str] = ..., session_id: _Optional[str] = ..., values_json: _Optional[str] = ...) -> None: ...

class AgentEvent(_message.Message):
    __slots__ = ("type", "data")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    type: str
    data: bytes
    def __init__(self, type: _Optional[str] = ..., data: _Optional[bytes] = ...) -> None: ...
