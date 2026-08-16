from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .conversation import ConversationState
from .skill import SkillFrontmatter
from .token_usage import TokenUsage


class AgentResources(BaseModel):
    """
    智能体静态资源

    参数:
        system_prompt: 智能体系统提示词
        skill_list: Skill列表
        skill_frontmatter_list: Skill Frontmatter 列表
        kb_list: 知识库列表
    """
    system_prompt: str | None = None
    skill_list: dict[str, Any] | None = Field(default_factory=dict)
    skill_frontmatter_list: dict[str, SkillFrontmatter] | None = Field(default_factory=dict)
    kb_list: dict[str, Any] | None = Field(default_factory=dict)


class AgentMode(Enum):
    """
    Agent 运行模式
    """
    ASK = "ask" # 问答模式：仅允许只读查询，不执行写入、修改、删除等操作
    AGENT = "agent" # 智能体模式：允许执行读写、创建、修改、删除等操作


class AgentState(BaseModel):
    """
    智能体状态

    参数:
        session_id: 会话ID
        conversation: 对话状态
        token_usage: 词元累计用量
    """
    session_id: str
    conversation: ConversationState = Field(default_factory=ConversationState)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class AgentResult(BaseModel):
    """
    Agent运行结果

    参数:
        text: Agent 最终输出文本
        reasoning: Agent 运行时中间思考过程文本
        token_usage: 本轮对话的词元消耗
    """
    text: str = Field(default="")
    reasoning: list[str] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    def apply_llm_result(self, content: str, token_usage: TokenUsage) -> None:
        """将一次 LLM 调用的思考内容与词元用量写入本轮 AgentResult。"""
        self.token_usage = self.token_usage.add(token_usage)
        if content:
            self.reasoning.append(content)
