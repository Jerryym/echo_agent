from typing import Any

from pydantic import BaseModel, Field

from .skill import SkillFrontmatter


class AgentResources(BaseModel):
    """
    智能体静态资源

    参数:
        system_prompt: 智能体系统提示词
        skill_list: Skill列表
        kb_list: 知识库列表
    """
    system_prompt: str | None = None
    skill_list: dict[str, SkillFrontmatter] = Field(default_factory=dict)
    kb_list: dict[str, Any] | None = Field(default_factory=dict)
