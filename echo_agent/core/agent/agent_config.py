from typing import Self

from pydantic import BaseModel, Field, model_validator

from ..llm import LLMConfig
from ..mcp import MCPConnectionConfig, builtin_mcp_servers


class AgentConfig(BaseModel):
    """
    Agent 配置

    参数:
        name: Agent 名称
        description: 描述
        llm_config: LLM 配置
        system_prompt: 系统提示词
        kb_list: 知识库列表
        skill_list: 技能列表
        enable_builtin_mcp: 是否自动附带内置 MCP（Fetch / Filesystem），默认 True
        mcp_allowed_directories: 内置 Filesystem 允许访问的目录；为 None 时使用 cwd
        mcp_servers: 额外 MCP Server 连接配置；同名覆盖内置，其余追加
    """
    name: str
    description: str | None = None

    llm_config: LLMConfig
    system_prompt: str | None = None

    kb_list: list[str] = Field(default_factory=list)
    skill_list: list[str] = Field(default_factory=list)

    enable_builtin_mcp: bool = True
    mcp_allowed_directories: str | list[str] | None = None
    mcp_servers: list[MCPConnectionConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _merge_builtin_mcp(self) -> Self:
        if not self.enable_builtin_mcp:
            return self

        builtin_list = builtin_mcp_servers(
            allowed_directories=self.mcp_allowed_directories,
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
