from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from ..llm.llm_config import LLMConfig
from ..mcp import MCPConnectionConfig, builtin_mcp_servers
from ..model.agent import AgentMode


class AgentConfig(BaseModel):
    """
    Agent 配置

    参数:
        name: Agent 名称
        description: 描述
        llm_config: LLM 配置
        system_prompt: 系统提示词
        mode: Agent 运行模式
        kb_list: 知识库列表
        skill_list: 技能列表
        mcp_allowed_directories: 内置 Filesystem 允许访问的目录；
            仅当 enable_builtin_filesystem=True 时必填
        mcp_servers: 额外 MCP Server 连接配置；同名覆盖内置，其余追加
        enable_builtin_fetch: 是否合并内置 Fetch MCP（默认关闭）
        enable_builtin_filesystem: 是否合并内置 Filesystem MCP（默认关闭）
        conversation_max_tokens: 对话最大词元数
    """
    name: str
    description: str | None = None

    llm_config: LLMConfig
    system_prompt: str | None = None
    mode: list[AgentMode] = Field(default_factory=lambda: [AgentMode.AGENT])

    kb_list: list[str] = Field(default_factory=list)
    skill_list: dict[str, Any] = Field(default_factory=dict)

    mcp_allowed_directories: str | list[str] | None = None
    mcp_servers: list[MCPConnectionConfig] = Field(default_factory=list)

    enable_builtin_fetch: bool = False
    enable_builtin_filesystem: bool = False

    conversation_max_tokens: int = 128000

    @model_validator(mode="after")
    def _merge_builtin_mcp(self) -> Self:
        if self.enable_builtin_filesystem:
            dirs = self.mcp_allowed_directories
            if dirs is None or (isinstance(dirs, str) and not dirs.strip()) or (
                isinstance(dirs, list) and not dirs
            ):
                raise ValueError(
                    "mcp_allowed_directories is required when "
                    "enable_builtin_filesystem is True"
                )

        builtin_list = builtin_mcp_servers(
            allowed_directories=self.mcp_allowed_directories or [],
            enable_fetch=self.enable_builtin_fetch,
            enable_filesystem=self.enable_builtin_filesystem,
        )
        user_by_name = {cfg.name: cfg for cfg in self.mcp_servers}
        builtin_names = {cfg.name for cfg in builtin_list}

        merged: list[MCPConnectionConfig] = [
            user_by_name.get(cfg.name, cfg) for cfg in builtin_list
        ]
        for cfg in self.mcp_servers:
            if cfg.name not in builtin_names:
                merged.append(cfg)

        self.mcp_servers = merged
        return self
