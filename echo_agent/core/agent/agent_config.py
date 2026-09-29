from typing import Mapping, Sequence

from pydantic import BaseModel, Field, field_validator

from ..llm.llm_config import LLMConfig
from ..mcp import MCPConnectionConfig
from ..model.agent import AgentMode
from ..model.skill import SkillSource


class AgentConfig(BaseModel):
    """
    Agent 配置

    参数:
        id: Agent ID
        name: Agent 名称
        description: 描述
        llm_config: LLM 配置
        system_prompt: 系统提示词
        mode: Agent 运行模式
        kb_list: 知识库列表
        skill_list: 技能列表
        allowed_directories: 允许访问的目录（保留字段；不驱动 MCP）
        mcp_servers: MCP Server 连接配置（全部显式声明，无内置预设）
        conversation_max_tokens: 对话最大词元数
    """
    id: str | None = None

    name: str
    description: str | None = None

    llm_config: LLMConfig
    system_prompt: str | None = None
    mode: list[AgentMode] = Field(default_factory=lambda: [AgentMode.AGENT])

    kb_list: list[str] = Field(default_factory=list)
    skill_list: list[SkillSource] = Field(default_factory=list)

    allowed_directories: str | list[str] | None = None
    mcp_servers: list[MCPConnectionConfig] = Field(default_factory=list)

    conversation_max_tokens: int = 256000

    @field_validator("skill_list", mode="before")
    @classmethod
    def _coerce_skill_list(cls, value: Mapping[str, str] | Sequence[SkillSource] | Sequence[Mapping[str, str]] | None) -> list[SkillSource]:
        if value is None:
            return []
        if isinstance(value, Mapping):
            return [SkillSource(name=name, url=url) for name, url in value.items()]
        return [
            item if isinstance(item, SkillSource) else SkillSource.model_validate(item)
            for item in value
        ]
