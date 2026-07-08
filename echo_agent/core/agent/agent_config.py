from pydantic import BaseModel, Field

from ..llm import LLMConfig
from ..strategy import StrategyType


class AgentConfig(BaseModel):
    """
    Agent 配置

    参数:
        name: Agent 名称
        description: 描述
        llm_config: LLM 配置
        system_prompt: 系统提示词
        strategy: 策略
        kb_list: 知识库列表
        skill_list: 技能列表
    """
    name: str
    description: str | None = None

    llm_config: LLMConfig
    system_prompt: str | None = None

    strategy: StrategyType | None = None

    kb_list: list[str] = Field(default_factory=list)
    skill_list: list[str] = Field(default_factory=list)